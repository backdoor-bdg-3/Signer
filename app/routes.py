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

main_bp = Blueprint('main', __name__)

ALLOWED_EXTENSIONS = {'ipa', 'mobileprovision', 'p12', 'zip', 'dylib'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@main_bp.route('/')
def index():
    return render_template('index.html', form=SigningForm())

@main_bp.route('/advanced')
def advanced():
    return render_template('advanced.html', form=AdvancedSigningForm())

@main_bp.route('/sign', methods=['POST'])
def sign_app():
    form = SigningForm()
    
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", "error")
        return redirect(url_for('main.index'))
    
    # Create a unique session ID for this signing request
    session_id = str(uuid.uuid4())
    session_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    # Save uploaded files
    ipa_file = form.ipa_file.data
    p12_file = form.p12_file.data
    provision_file = form.provision_file.data
    
    ipa_filename = secure_filename(ipa_file.filename)
    p12_filename = secure_filename(p12_file.filename)
    provision_filename = secure_filename(provision_file.filename)
    
    ipa_path = os.path.join(session_dir, ipa_filename)
    p12_path = os.path.join(session_dir, p12_filename)
    provision_path = os.path.join(session_dir, provision_filename)
    
    ipa_file.save(ipa_path)
    p12_file.save(p12_path)
    provision_file.save(provision_path)
    
    # Save app icon if provided
    icon_path = None
    if form.app_icon.data and form.app_icon.data.filename:
        icon_file = form.app_icon.data
        icon_filename = secure_filename(icon_file.filename)
        icon_path = os.path.join(session_dir, icon_filename)
        icon_file.save(icon_path)
    
    # Extract app info from IPA for OTA manifest
    app_info = extract_app_info(ipa_path)
    
    # Output path for signed IPA
    output_filename = f"signed_{os.path.basename(ipa_path)}"
    output_path = os.path.join(current_app.config['SIGNED_FOLDER'], output_filename)
    
    # Execute zsign command
    try:
        cmd = [
            'zsign', 
            '-k', p12_path, 
            '-p', form.p12_password.data, 
            '-m', provision_path, 
            '-o', output_path, 
            '-z', '9'  # Compression level
        ]
        
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
        
        # Generate OTA manifest and installation URL
        manifest_filename = f"manifest_{session_id}.plist"
        manifest_path = os.path.join(current_app.config['SIGNED_FOLDER'], manifest_filename)
        
        # Create OTA manifest
        create_ota_manifest(
            manifest_path,
            app_info,
            request.host_url + url_for('main.download_file', filename=output_filename)[1:],
            output_filename
        )
        
        # Generate OTA installation URL
        ota_url = f"itms-services://?action=download-manifest&url={request.host_url}{url_for('main.download_manifest', filename=manifest_filename)[1:]}"
        
        # Clean up uploaded files
        shutil.rmtree(session_dir)
        
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
    session_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    # Save uploaded files
    ipa_file = form.ipa_file.data
    p12_file = form.p12_file.data
    provision_file = form.provision_file.data
    
    ipa_filename = secure_filename(ipa_file.filename)
    p12_filename = secure_filename(p12_file.filename)
    provision_filename = secure_filename(provision_file.filename)
    
    ipa_path = os.path.join(session_dir, ipa_filename)
    p12_path = os.path.join(session_dir, p12_filename)
    provision_path = os.path.join(session_dir, provision_filename)
    
    ipa_file.save(ipa_path)
    p12_file.save(p12_path)
    provision_file.save(provision_path)
    
    # Save app icon if provided
    icon_path = None
    if form.app_icon.data and form.app_icon.data.filename:
        icon_file = form.app_icon.data
        icon_filename = secure_filename(icon_file.filename)
        icon_path = os.path.join(session_dir, icon_filename)
        icon_file.save(icon_path)
    
    # Handle optional dylib files
    dylib_paths = []
    if form.dylib_files.data:
        for dylib_file in form.dylib_files.data:
            if dylib_file.filename:
                dylib_filename = secure_filename(dylib_file.filename)
                dylib_path = os.path.join(session_dir, dylib_filename)
                dylib_file.save(dylib_path)
                dylib_paths.append(dylib_path)
    
    # Extract app info from IPA for OTA manifest
    app_info = extract_app_info(ipa_path)
    
    # Output path for signed IPA
    output_filename = f"signed_{os.path.basename(ipa_path)}"
    output_path = os.path.join(current_app.config['SIGNED_FOLDER'], output_filename)
    
    # Execute zsign command
    try:
        cmd = [
            'zsign', 
            '-k', p12_path, 
            '-p', form.p12_password.data, 
            '-m', provision_path, 
            '-o', output_path
        ]
        
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
            entitlements_path = os.path.join(session_dir, 'entitlements.plist')
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
        
        # Generate OTA manifest and installation URL
        manifest_filename = f"manifest_{session_id}.plist"
        manifest_path = os.path.join(current_app.config['SIGNED_FOLDER'], manifest_filename)
        
        # Create OTA manifest
        create_ota_manifest(
            manifest_path,
            app_info,
            request.host_url + url_for('main.download_file', filename=output_filename)[1:],
            output_filename
        )
        
        # Generate OTA installation URL
        ota_url = f"itms-services://?action=download-manifest&url={request.host_url}{url_for('main.download_manifest', filename=manifest_filename)[1:]}"
        
        # Clean up uploaded files
        shutil.rmtree(session_dir)
        
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
    return send_from_directory(current_app.config['SIGNED_FOLDER'], filename, as_attachment=True)

@main_bp.route('/manifest/<filename>')
def download_manifest(filename):
    return send_from_directory(current_app.config['SIGNED_FOLDER'], filename, mimetype='application/xml')

@main_bp.route('/install/<filename>')
def install_app(filename):
    """Display QR code and installation instructions for OTA installation"""
    if not os.path.exists(os.path.join(current_app.config['SIGNED_FOLDER'], filename)):
        flash("File not found", "error")
        return redirect(url_for('main.index'))
    
    # Generate manifest filename
    manifest_filename = f"manifest_{filename.replace('signed_', '')}.plist"
    manifest_path = os.path.join(current_app.config['SIGNED_FOLDER'], manifest_filename)
    
    # Create manifest if it doesn't exist
    if not os.path.exists(manifest_path):
        app_info = extract_app_info(os.path.join(current_app.config['SIGNED_FOLDER'], filename))
        create_ota_manifest(
            manifest_path,
            app_info,
            request.host_url + url_for('main.download_file', filename=filename)[1:],
            filename
        )
    
    # Generate OTA installation URL
    ota_url = f"itms-services://?action=download-manifest&url={request.host_url}{url_for('main.download_manifest', filename=manifest_filename)[1:]}"
    
    return render_template('install.html', filename=filename, ota_url=ota_url)

@main_bp.route('/about')
def about():
    return render_template('about.html')

@main_bp.route('/contact')
def contact():
    return render_template('contact.html')

@main_bp.route('/extract-entitlements', methods=['POST'])
def extract_entitlements():
    """Extract entitlements from uploaded IPA and provisioning profile"""
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
        
        try:
            # Save uploaded files
            ipa_path = os.path.join(temp_dir, secure_filename(ipa_file.filename))
            provision_path = os.path.join(temp_dir, secure_filename(provision_file.filename))
            
            ipa_file.save(ipa_path)
            provision_file.save(provision_path)
            
            # Extract entitlements
            app_entitlements = extract_app_entitlements(ipa_path)
            provision_entitlements = extract_provision_entitlements(provision_path)
            
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
            
            return jsonify({
                'app_entitlements': app_entitlements,
                'provision_entitlements': provision_entitlements,
                'all_entitlements': all_entitlements
            })
            
        finally:
            # Clean up temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500