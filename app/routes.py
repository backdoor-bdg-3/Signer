import os
import uuid
import subprocess
import shutil
import json
import plistlib
import zipfile
import base64
import re
import tempfile
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, current_app, Response, session
from werkzeug.utils import secure_filename
from app.forms import SigningForm, AdvancedSigningForm
from app.utils.storage import storage_manager

main_bp = Blueprint('main', __name__)

ALLOWED_EXTENSIONS = {'ipa', 'mobileprovision', 'p12', 'zip', 'dylib'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/basic')
def basic_signing():
    return render_template('basic_signing.html', form=SigningForm())

@main_bp.route('/advanced')
def advanced():
    return render_template('advanced.html', form=AdvancedSigningForm())

@main_bp.route('/entitlements')
def entitlements():
    return render_template('entitlements.html')

@main_bp.route('/sign', methods=['POST'])
def sign_app():
    form = SigningForm()
    
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", "error")
        return redirect(url_for('main.basic_signing'))
    
    # Create a unique session ID for this signing request
    session_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Save uploaded files using storage manager
        ipa_file = form.ipa_file.data
        p12_file = form.p12_file.data
        provision_file = form.provision_file.data
        
        # Save files to temporary directory first
        ipa_filename = secure_filename(ipa_file.filename)
        p12_filename = secure_filename(p12_file.filename)
        provision_filename = secure_filename(provision_file.filename)
        
        ipa_path = os.path.join(temp_dir, ipa_filename)
        p12_path = os.path.join(temp_dir, p12_filename)
        provision_path = os.path.join(temp_dir, provision_filename)
        
        ipa_file.save(ipa_path)
        p12_file.save(p12_path)
        provision_file.save(provision_path)
        
        # Save app icon if provided
        icon_path = None
        if form.app_icon.data and form.app_icon.data.filename:
            icon_file = form.app_icon.data
            icon_filename = secure_filename(icon_file.filename)
            icon_path = os.path.join(temp_dir, icon_filename)
            icon_file.save(icon_path)
        
        # Extract app info from IPA for OTA manifest
        app_info = extract_app_info(ipa_path)
        
        # Output path for signed IPA
        output_filename = f"signed_{os.path.basename(ipa_path)}"
        output_path = os.path.join(temp_dir, output_filename)
        
        # Extract provision info to check for Apple Developer certificate
        provision_info = extract_udids_from_provision(provision_path)
        
        # Execute zsign command - use full path to ensure it's found
        zsign_path = '/usr/local/bin/zsign'
        if not os.path.exists(zsign_path):
            # Fall back to PATH resolution if the direct path doesn't exist
            zsign_path = shutil.which('zsign')
            if not zsign_path:
                # Last resort - try the symlink location
                if os.path.exists('/usr/bin/zsign'):
                    zsign_path = '/usr/bin/zsign'
                else:
                    flash(f"zsign executable not found. Please check installation.", "error")
                    return redirect(url_for('main.index'))
                
        cmd = [
            zsign_path, 
            '-k', p12_path, 
            '-p', form.p12_password.data, 
            '-m', provision_path, 
            '-o', output_path, 
            '-z', '9'  # Compression level
        ]
        
        # If this is an Apple Developer certificate with UDID, add force flag
        if provision_info.get('is_developer_profile', False) and provision_info.get('udids', []):
            cmd.append('-f')  # Force sign even with UDID restrictions
        
        # Add optional parameters if provided
        if form.bundle_id.data:
            cmd.extend(['-b', form.bundle_id.data])
        
        if form.bundle_name.data:
            cmd.extend(['-n', form.bundle_name.data])
        
        if form.bundle_version.data:
            cmd.extend(['-v', form.bundle_version.data])
        
        # Add the IPA path at the end
        cmd.append(ipa_path)
        
        # Execute the command and capture output
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            flash(f"Error signing app: {stderr}", "error")
            return redirect(url_for('main.index'))
        
        # Store the signed IPA using Git LFS
        with open(output_path, 'rb') as f:
            success, stored_path = storage_manager.save_file(f, 'signed', output_filename)
            if not success:
                flash(f"Error storing signed IPA: {stored_path}", "error")
                return redirect(url_for('main.index'))
        
        # Generate OTA manifest and installation URL
        manifest_filename = f"manifest_{session_id}.plist"
        manifest_path = os.path.join(temp_dir, manifest_filename)
        
        # Get the URL for the stored IPA
        ipa_url = request.host_url + url_for('main.download_file', filename=output_filename)[1:]
        
        # Create OTA manifest
        create_ota_manifest(
            manifest_path,
            app_info,
            ipa_url,
            output_filename
        )
        
        # Store the manifest using Git LFS
        with open(manifest_path, 'rb') as f:
            success, manifest_stored_path = storage_manager.save_file(f, 'manifests', manifest_filename)
            if not success:
                flash(f"Error storing manifest: {manifest_stored_path}", "error")
                return redirect(url_for('main.index'))
        
        # Generate OTA installation URL
        ota_url = f"itms-services://?action=download-manifest&url={request.host_url}{url_for('main.download_manifest', filename=manifest_filename)[1:]}"
        
        # Return the download URL and OTA URL
        download_url = url_for('main.download_file', filename=output_filename)
        return render_template(
            'success.html', 
            download_url=download_url, 
            ota_url=ota_url,
            filename=output_filename,
            app_info=app_info
        )
    
    except Exception as e:
        flash(f"Error during signing process: {str(e)}", "error")
        return redirect(url_for('main.index'))
    
    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)

@main_bp.route('/sign/advanced', methods=['POST'])
def sign_app_advanced():
    form = AdvancedSigningForm()
    
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", "error")
        return redirect(url_for('main.advanced'))
    
    # Create a unique session ID for this signing request
    session_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Save uploaded files
        ipa_file = form.ipa_file.data
        p12_file = form.p12_file.data
        provision_file = form.provision_file.data
        
        # Save files to temporary directory first
        ipa_filename = secure_filename(ipa_file.filename)
        p12_filename = secure_filename(p12_file.filename)
        provision_filename = secure_filename(provision_file.filename)
        
        ipa_path = os.path.join(temp_dir, ipa_filename)
        p12_path = os.path.join(temp_dir, p12_filename)
        provision_path = os.path.join(temp_dir, provision_filename)
        
        ipa_file.save(ipa_path)
        p12_file.save(p12_path)
        provision_file.save(provision_path)
        
        # Save app icon if provided
        icon_path = None
        if form.app_icon.data and form.app_icon.data.filename:
            icon_file = form.app_icon.data
            icon_filename = secure_filename(icon_file.filename)
            icon_path = os.path.join(temp_dir, icon_filename)
            icon_file.save(icon_path)
        
        # Handle optional dylib files
        dylib_paths = []
        if form.dylib_files.data:
            for dylib_file in form.dylib_files.data:
                if dylib_file.filename:
                    dylib_filename = secure_filename(dylib_file.filename)
                    dylib_path = os.path.join(temp_dir, dylib_filename)
                    dylib_file.save(dylib_path)
                    dylib_paths.append(dylib_path)
        
        # Extract app info from IPA for OTA manifest
        app_info = extract_app_info(ipa_path)
        
        # Output path for signed IPA
        output_filename = f"signed_{os.path.basename(ipa_path)}"
        output_path = os.path.join(temp_dir, output_filename)
        
        # Extract provision info to check for Apple Developer certificate
        provision_info = extract_udids_from_provision(provision_path)
        
        # Execute zsign command - use full path to ensure it's found
        zsign_path = '/usr/local/bin/zsign'
        if not os.path.exists(zsign_path):
            # Fall back to PATH resolution if the direct path doesn't exist
            zsign_path = shutil.which('zsign')
            if not zsign_path:
                # Last resort - try the symlink location
                if os.path.exists('/usr/bin/zsign'):
                    zsign_path = '/usr/bin/zsign'
                else:
                    flash(f"zsign executable not found. Please check installation.", "error")
                    return redirect(url_for('main.advanced'))
                
        cmd = [
            zsign_path, 
            '-k', p12_path, 
            '-p', form.p12_password.data, 
            '-m', provision_path, 
            '-o', output_path
        ]
        
        # If this is an Apple Developer certificate with UDID, add force flag
        if provision_info.get('is_developer_profile', False) and provision_info.get('udids', []):
            cmd.append('-f')  # Force sign even with UDID restrictions
        
        # Add optional parameters
        if form.bundle_id.data:
            cmd.extend(['-b', form.bundle_id.data])
        
        if form.bundle_name.data:
            cmd.extend(['-n', form.bundle_name.data])
        
        if form.bundle_version.data:
            cmd.extend(['-v', form.bundle_version.data])
            
        # Add app icon if provided
        if icon_path:
            cmd.extend(['-i', icon_path])
        
        if form.entitlements.data:
            entitlements_path = os.path.join(temp_dir, 'entitlements.plist')
            with open(entitlements_path, 'w') as f:
                f.write(form.entitlements.data)
            cmd.extend(['-e', entitlements_path])
        
        # Add compression level
        compression = form.compression_level.data or '9'
        cmd.extend(['-z', compression])
        
        # Add dylib injection if provided
        for dylib_path in dylib_paths:
            cmd.extend(['-l', dylib_path])
        
        # Add weak signature option if selected
        if form.weak_signature.data:
            cmd.append('-w')
        
        # Add force signature option if selected
        if form.force_signature.data:
            cmd.append('-f')
        
        # Add verbose option if selected
        if form.verbose.data:
            cmd.append('-v')
        
        # Add the IPA path at the end
        cmd.append(ipa_path)
        
        # Execute the command and capture output
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            flash(f"Error signing app: {stderr}", "error")
            return redirect(url_for('main.advanced'))
        
        # Store the signed IPA using Git LFS
        with open(output_path, 'rb') as f:
            success, stored_path = storage_manager.save_file(f, 'signed', output_filename)
            if not success:
                flash(f"Error storing signed IPA: {stored_path}", "error")
                return redirect(url_for('main.advanced'))
        
        # Generate OTA manifest and installation URL
        manifest_filename = f"manifest_{session_id}.plist"
        manifest_path = os.path.join(temp_dir, manifest_filename)
        
        # Get the URL for the stored IPA
        ipa_url = request.host_url + url_for('main.download_file', filename=output_filename)[1:]
        
        # Create OTA manifest
        create_ota_manifest(
            manifest_path,
            app_info,
            ipa_url,
            output_filename
        )
        
        # Store the manifest using Git LFS
        with open(manifest_path, 'rb') as f:
            success, manifest_stored_path = storage_manager.save_file(f, 'manifests', manifest_filename)
            if not success:
                flash(f"Error storing manifest: {manifest_stored_path}", "error")
                return redirect(url_for('main.advanced'))
        
        # Generate OTA installation URL
        ota_url = f"itms-services://?action=download-manifest&url={request.host_url}{url_for('main.download_manifest', filename=manifest_filename)[1:]}"
        
        # Return the download URL and OTA URL
        download_url = url_for('main.download_file', filename=output_filename)
        return render_template(
            'success.html', 
            download_url=download_url, 
            ota_url=ota_url,
            filename=output_filename,
            app_info=app_info,
            stdout=stdout
        )
    
    except Exception as e:
        flash(f"Error during signing process: {str(e)}", "error")
        return redirect(url_for('main.advanced'))
    
    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)

def extract_app_info(ipa_path):
    """Extract app information from IPA file for OTA manifest"""
    try:
        app_info = {
            'bundle_id': '',
            'bundle_name': '',
            'bundle_version': '',
            'icon_base64': ''
        }
        
        with zipfile.ZipFile(ipa_path, 'r') as zip_ref:
            # Find Info.plist
            info_plist_path = None
            for file_path in zip_ref.namelist():
                if 'Info.plist' in file_path and '/Payload/' in file_path:
                    info_plist_path = file_path
                    break
            
            if not info_plist_path:
                return app_info
            
            # Extract and parse Info.plist
            with zip_ref.open(info_plist_path) as info_file:
                info_data = info_file.read()
                info = plistlib.loads(info_data)
                
                app_info['bundle_id'] = info.get('CFBundleIdentifier', '')
                app_info['bundle_name'] = info.get('CFBundleDisplayName', info.get('CFBundleName', ''))
                app_info['bundle_version'] = info.get('CFBundleShortVersionString', '')
                
                # Find app icon
                icon_name = None
                if 'CFBundleIcons' in info and 'CFBundlePrimaryIcon' in info['CFBundleIcons']:
                    icon_files = info['CFBundleIcons']['CFBundlePrimaryIcon'].get('CFBundleIconFiles', [])
                    if icon_files:
                        icon_name = icon_files[-1]  # Use the largest icon
                
                if icon_name:
                    # Find the icon file
                    app_dir = os.path.dirname(info_plist_path)
                    for file_path in zip_ref.namelist():
                        if file_path.startswith(app_dir) and icon_name in file_path and file_path.endswith('.png'):
                            with zip_ref.open(file_path) as icon_file:
                                icon_data = icon_file.read()
                                app_info['icon_base64'] = base64.b64encode(icon_data).decode('utf-8')
                                break
        
        return app_info
    
    except Exception as e:
        print(f"Error extracting app info: {str(e)}")
        return app_info

def extract_app_entitlements(ipa_path):
    """Extract entitlements from the IPA file"""
    try:
        # Create a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            # Extract the IPA
            with zipfile.ZipFile(ipa_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            # Find the app directory
            app_dir = None
            payload_dir = os.path.join(temp_dir, 'Payload')
            if os.path.exists(payload_dir):
                for item in os.listdir(payload_dir):
                    if item.endswith('.app'):
                        app_dir = os.path.join(payload_dir, item)
                        break
            
            if not app_dir:
                return {}
            
            # Find embedded.mobileprovision
            provision_path = os.path.join(app_dir, 'embedded.mobileprovision')
            if os.path.exists(provision_path):
                return extract_provision_entitlements(provision_path)
            
            return {}
    except Exception as e:
        print(f"Error extracting app entitlements: {str(e)}")
        return {}

def extract_provision_entitlements(provision_path):
    """Extract entitlements from a provisioning profile"""
    try:
        # Read the provisioning profile
        with open(provision_path, 'rb') as f:
            data = f.read()
        
        # Extract the plist data
        pattern = b'<plist.*?</plist>'
        match = re.search(pattern, data, re.DOTALL)
        
        if not match:
            return {}
        
        plist_data = match.group(0)
        
        # Parse the plist
        provision = plistlib.loads(plist_data)
        
        # Get the entitlements
        entitlements = provision.get('Entitlements', {})
        return entitlements
    except Exception as e:
        print(f"Error extracting provision entitlements: {str(e)}")
        return {}
        
def extract_udids_from_provision(provision_path):
    """Extract UDIDs from a provisioning profile"""
    try:
        # Read the provisioning profile
        with open(provision_path, 'rb') as f:
            data = f.read()

        # Extract the plist data
        pattern = b'<plist.*?</plist>'
        match = re.search(pattern, data, re.DOTALL)

        if not match:
            return {'udids': [], 'is_developer_profile': False}

        plist_data = match.group(0)

        # Parse the plist
        provision = plistlib.loads(plist_data)
        
        # Get the provisioned devices
        udids = provision.get('ProvisionedDevices', [])
        
        # Check if this is a development profile with PPQ check
        is_developer_profile = False
        profile_type = provision.get('ProvisionsAllDevices', False)
        if not profile_type:
            # Check for developer certificate
            certificates = provision.get('DeveloperCertificates', [])
            for cert_data in certificates:
                # Check if it's an Apple Developer certificate
                if b'Apple Development' in cert_data or b'iPhone Developer' in cert_data:
                    is_developer_profile = True
                    break
        
        return {
            'udids': udids,
            'is_developer_profile': is_developer_profile,
            'profile_name': provision.get('Name', ''),
            'team_name': provision.get('TeamName', ''),
            'creation_date': provision.get('CreationDate', '').isoformat() if provision.get('CreationDate') else '',
            'expiration_date': provision.get('ExpirationDate', '').isoformat() if provision.get('ExpirationDate') else '',
            'app_id_name': provision.get('AppIDName', ''),
            'platform': provision.get('Platform', []),
        }
    except Exception as e:
        print(f"Error extracting UDIDs from provision: {str(e)}")
        return {'udids': [], 'is_developer_profile': False}

def create_ota_manifest(manifest_path, app_info, ipa_url, ipa_filename):
    """Create OTA installation manifest plist file"""
    try:
        manifest = {
            'items': [{
                'assets': [{
                    'kind': 'software-package',
                    'url': ipa_url
                }],
                'metadata': {
                    'bundle-identifier': app_info['bundle_id'],
                    'bundle-version': app_info['bundle_version'],
                    'kind': 'software',
                    'title': app_info['bundle_name'] or ipa_filename
                }
            }]
        }
        
        # Add app icon if available
        if app_info['icon_base64']:
            manifest['items'][0]['assets'].append({
                'kind': 'display-image',
                'needs-shine': True,
                'url': f"data:image/png;base64,{app_info['icon_base64']}"
            })
            manifest['items'][0]['assets'].append({
                'kind': 'full-size-image',
                'needs-shine': True,
                'url': f"data:image/png;base64,{app_info['icon_base64']}"
            })
        
        with open(manifest_path, 'wb') as f:
            plistlib.dump(manifest, f)
    
    except Exception as e:
        print(f"Error creating OTA manifest: {str(e)}")

@main_bp.route('/download/<filename>')
def download_file(filename):
    # Get the file path from storage manager
    file_path = storage_manager.get_file(os.path.join('signed', filename))
    if not file_path:
        flash("File not found", "error")
        return redirect(url_for('main.index'))
    
    # Get the directory and filename
    directory, filename = os.path.split(file_path)
    return send_from_directory(directory, filename, as_attachment=True)

@main_bp.route('/manifest/<filename>')
def download_manifest(filename):
    # Get the file path from storage manager
    file_path = storage_manager.get_file(os.path.join('manifests', filename))
    if not file_path:
        flash("Manifest not found", "error")
        return redirect(url_for('main.index'))
    
    # Get the directory and filename
    directory, filename = os.path.split(file_path)
    return send_from_directory(directory, filename, mimetype='application/xml')

@main_bp.route('/install/<filename>')
def install_app(filename):
    """Display QR code and installation instructions for OTA installation"""
    # Check if the file exists in storage
    file_path = storage_manager.get_file(os.path.join('signed', filename))
    if not file_path:
        flash("File not found", "error")
        return redirect(url_for('main.index'))
    
    # Generate manifest filename
    manifest_filename = f"manifest_{filename.replace('signed_', '')}.plist"
    
    # Check if manifest exists
    manifest_path = storage_manager.get_file(os.path.join('manifests', manifest_filename))
    
    # Create manifest if it doesn't exist
    if not manifest_path:
        # Create a temporary directory for the manifest
        temp_dir = tempfile.mkdtemp()
        try:
            temp_manifest_path = os.path.join(temp_dir, manifest_filename)
            
            # Extract app info from the IPA
            app_info = extract_app_info(file_path)
            
            # Create OTA manifest
            create_ota_manifest(
                temp_manifest_path,
                app_info,
                request.host_url + url_for('main.download_file', filename=filename)[1:],
                filename
            )
            
            # Store the manifest using Git LFS
            with open(temp_manifest_path, 'rb') as f:
                success, manifest_stored_path = storage_manager.save_file(f, 'manifests', manifest_filename)
                if not success:
                    flash(f"Error storing manifest: {manifest_stored_path}", "error")
                    return redirect(url_for('main.index'))
        finally:
            # Clean up temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    # Generate OTA installation URL
    ota_url = f"itms-services://?action=download-manifest&url={request.host_url}{url_for('main.download_manifest', filename=manifest_filename)[1:]}"
    
    return render_template('install.html', filename=filename, ota_url=ota_url)

@main_bp.route('/about')
def about():
    return render_template('about.html')

@main_bp.route('/contact')
def contact():
    return render_template('contact.html')

@main_bp.route('/entitlements')
def entitlements_page():
    """Display the entitlements management page"""
    return render_template('entitlements.html')

@main_bp.route('/extract-entitlements', methods=['POST'])
def extract_entitlements():
    """Extract entitlements from uploaded IPA and provisioning profile"""
    temp_dir = None
    try:
        # Check if files were uploaded
        if 'ipa_file' not in request.files or 'provision_file' not in request.files:
            return jsonify({'error': 'Missing required files'}), 400
        
        ipa_file = request.files['ipa_file']
        provision_file = request.files['provision_file']
        
        if ipa_file.filename == '' or provision_file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        print(f"Created temp directory: {temp_dir}")
        
        try:
            # Save uploaded files
            ipa_path = os.path.join(temp_dir, secure_filename(ipa_file.filename))
            provision_path = os.path.join(temp_dir, secure_filename(provision_file.filename))
            
            print(f"Saving IPA to: {ipa_path}")
            ipa_file.save(ipa_path)
            print(f"Saving provision to: {provision_path}")
            provision_file.save(provision_path)
            
            # Verify files were saved correctly
            if not os.path.exists(ipa_path) or os.path.getsize(ipa_path) == 0:
                return jsonify({'error': 'Failed to save IPA file properly'}), 500
                
            if not os.path.exists(provision_path) or os.path.getsize(provision_path) == 0:
                return jsonify({'error': 'Failed to save provision file properly'}), 500
            
            # Generate a unique session ID
            session_id = str(uuid.uuid4())
            
            # Store files temporarily (with error handling)
            try:
                print(f"Storing IPA file in storage manager")
                with open(ipa_path, 'rb') as f:
                    success, ipa_stored_path = storage_manager.save_file(f, 'temp', f"{session_id}_{os.path.basename(ipa_path)}")
                    if not success:
                        print(f"Warning: Failed to store IPA file: {ipa_stored_path}")
            except Exception as store_err:
                print(f"Error storing IPA file: {str(store_err)}")
                # Continue even if storage fails
            
            try:
                print(f"Storing provision file in storage manager")
                with open(provision_path, 'rb') as f:
                    success, prov_stored_path = storage_manager.save_file(f, 'temp', f"{session_id}_{os.path.basename(provision_path)}")
                    if not success:
                        print(f"Warning: Failed to store provision file: {prov_stored_path}")
            except Exception as store_err:
                print(f"Error storing provision file: {str(store_err)}")
                # Continue even if storage fails
            
            # Extract entitlements with better error handling
            try:
                print(f"Extracting app entitlements")
                app_entitlements = extract_app_entitlements(ipa_path)
                print(f"Found {len(app_entitlements)} app entitlements")
            except Exception as app_err:
                print(f"Error extracting app entitlements: {str(app_err)}")
                app_entitlements = {}
            
            try:
                print(f"Extracting provision entitlements")
                provision_entitlements = extract_provision_entitlements(provision_path)
                print(f"Found {len(provision_entitlements)} provision entitlements")
            except Exception as prov_err:
                print(f"Error extracting provision entitlements: {str(prov_err)}")
                provision_entitlements = {}
            
            # Extract UDID information
            try:
                print(f"Extracting UDID information")
                provision_info = extract_udids_from_provision(provision_path)
            except Exception as udid_err:
                print(f"Error extracting UDIDs: {str(udid_err)}")
                provision_info = {}
            
            # Compare entitlements
            all_entitlements = {}
            
            # Add all entitlements from both sources
            for key, value in app_entitlements.items():
                all_entitlements[key] = {
                    'value': value,
                    'in_app': True,
                    'in_provision': key in provision_entitlements
                }
            
            for key, value in provision_entitlements.items():
                if key not in all_entitlements:
                    all_entitlements[key] = {
                        'value': value,
                        'in_app': False,
                        'in_provision': True
                    }
            
            print(f"Successfully processed entitlements")
            return jsonify({
                'app_entitlements': app_entitlements,
                'provision_entitlements': provision_entitlements,
                'all_entitlements': all_entitlements,
                'provision_info': provision_info,
                'session_id': session_id
            })
            
        except Exception as inner_err:
            print(f"Inner error in extract_entitlements: {str(inner_err)}")
            return jsonify({'error': f"Error processing files: {str(inner_err)}"}), 500
            
        finally:
            # Clean up temporary directory
            if temp_dir and os.path.exists(temp_dir):
                print(f"Cleaning up temp directory: {temp_dir}")
                shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        print(f"Outer error in extract_entitlements: {str(e)}")
        # Make sure we clean up in case of exception
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({'error': f"Server error: {str(e)}"}), 500