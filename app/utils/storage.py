import os
import subprocess
import logging
import tempfile
import shutil
import uuid
import io
from werkzeug.utils import secure_filename
from flask import current_app, url_for, has_app_context

logger = logging.getLogger(__name__)

class GitLFSStorageManager:
    """
    Handles file storage operations using Git LFS for large files
    """
    
    def __init__(self):
        self.lfs_enabled = self._check_git_lfs_installed()
        self.lfs_repo_path = os.environ.get('LFS_REPO_PATH', '/tmp/lfs_storage')
        self.temp_dir = tempfile.mkdtemp()
        
        # Initialize Git LFS repository if it doesn't exist
        if self.lfs_enabled:
            self._init_lfs_repo()
    
    def _check_git_lfs_installed(self):
        """Check if Git LFS is installed"""
        try:
            result = subprocess.run(['git', 'lfs', 'version'], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE, 
                                   text=True)
            if result.returncode == 0:
                logger.info(f"Git LFS is installed: {result.stdout.strip()}")
                return True
            else:
                logger.warning("Git LFS is not installed or not working properly")
                return False
        except Exception as e:
            logger.error(f"Error checking Git LFS: {str(e)}")
            return False
    
    def _init_lfs_repo(self):
        """Initialize Git LFS repository"""
        try:
            # Create repository directory if it doesn't exist
            os.makedirs(self.lfs_repo_path, exist_ok=True)
            
            # Check if it's already a git repository
            if not os.path.exists(os.path.join(self.lfs_repo_path, '.git')):
                # Initialize git repository
                subprocess.run(['git', 'init'], cwd=self.lfs_repo_path, check=True)
                
                # Configure Git LFS
                subprocess.run(['git', 'lfs', 'install'], cwd=self.lfs_repo_path, check=True)
                
                # Create .gitattributes file to track large files
                with open(os.path.join(self.lfs_repo_path, '.gitattributes'), 'w') as f:
                    f.write("*.ipa filter=lfs diff=lfs merge=lfs -text\n")
                    f.write("*.mobileprovision filter=lfs diff=lfs merge=lfs -text\n")
                    f.write("*.p12 filter=lfs diff=lfs merge=lfs -text\n")
                
                # Add and commit .gitattributes
                subprocess.run(['git', 'add', '.gitattributes'], cwd=self.lfs_repo_path, check=True)
                subprocess.run(['git', 'config', 'user.email', 'backdoor@signer.app'], cwd=self.lfs_repo_path, check=True)
                subprocess.run(['git', 'config', 'user.name', 'Backdoor Signer'], cwd=self.lfs_repo_path, check=True)
                subprocess.run(['git', 'commit', '-m', 'Initialize Git LFS repository'], cwd=self.lfs_repo_path, check=True)
                
                logger.info(f"Git LFS repository initialized at {self.lfs_repo_path}")
            else:
                logger.info(f"Git LFS repository already exists at {self.lfs_repo_path}")
        except Exception as e:
            logger.error(f"Error initializing Git LFS repository: {str(e)}")
            self.lfs_enabled = False
    
    def save_file(self, file_obj, directory, filename=None):
        """
        Save a file using Git LFS
        
        Args:
            file_obj: The file object to save
            directory: The directory to save the file to (relative to LFS repo)
            filename: Optional filename, if not provided will use the original filename
            
        Returns:
            tuple: (success, filepath)
        """
        if filename is None:
            if hasattr(file_obj, 'filename'):
                filename = secure_filename(file_obj.filename)
            else:
                filename = f"file_{str(uuid.uuid4())[:8]}"
        
        # Generate a unique ID to avoid filename collisions
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{unique_id}_{filename}"
        
        # Create directory structure in LFS repo
        lfs_directory = os.path.join(self.lfs_repo_path, directory)
        os.makedirs(lfs_directory, exist_ok=True)
        
        # Full path to save the file
        filepath = os.path.join(lfs_directory, filename)
        
        try:
            # Save the file
            if hasattr(file_obj, 'save'):
                file_obj.save(filepath)
            elif hasattr(file_obj, 'read'):
                # Handle file-like objects (BytesIO, etc.)
                with open(filepath, 'wb') as f:
                    f.write(file_obj.read())
                # Reset file pointer if possible
                if hasattr(file_obj, 'seek'):
                    file_obj.seek(0)
            else:
                raise ValueError("Unsupported file object type")
                
            logger.info(f"File saved to {filepath}")
            
            if self.lfs_enabled:
                # Add file to Git LFS
                subprocess.run(['git', 'add', filepath], cwd=self.lfs_repo_path, check=True)
                
                # Commit the file
                commit_message = f"Add {filename} to {directory}"
                subprocess.run(['git', 'commit', '-m', commit_message], cwd=self.lfs_repo_path, check=True)
                
                logger.info(f"File {filename} added to Git LFS")
            
            # Return the relative path within the LFS repo
            rel_path = os.path.join(directory, filename)
            return True, rel_path
        except Exception as e:
            logger.error(f"Error saving file to Git LFS: {str(e)}")
            
            # Fallback to local storage if Git LFS fails
            try:
                # Determine static folder path
                static_folder = None
                if has_app_context():
                    static_folder = current_app.static_folder
                else:
                    # Default static folder if outside app context
                    static_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
                
                # Create local directory
                local_dir = os.path.join(static_folder, directory)
                os.makedirs(local_dir, exist_ok=True)
                
                # Save file locally
                local_path = os.path.join(local_dir, filename)
                if os.path.exists(filepath):
                    shutil.copy(filepath, local_path)
                elif hasattr(file_obj, 'save'):
                    file_obj.save(local_path)
                elif hasattr(file_obj, 'read'):
                    # Handle file-like objects
                    if hasattr(file_obj, 'seek'):
                        file_obj.seek(0)  # Reset file pointer
                    with open(local_path, 'wb') as f:
                        f.write(file_obj.read())
                
                logger.info(f"File saved locally to {local_path}")
                return True, os.path.join(directory, filename)
            except Exception as local_err:
                logger.error(f"Error saving file locally: {str(local_err)}")
                return False, str(local_err)
    
    def get_file(self, file_path):
        """
        Get a file from Git LFS
        
        Args:
            file_path: The relative path to the file in the LFS repo
            
        Returns:
            str: Path to the file
        """
        # Check if it's a full path or relative path
        if os.path.isabs(file_path):
            # If it's already a full path and exists, return it
            if os.path.exists(file_path):
                return file_path
            
            # Try to extract the relative path
            try:
                rel_path = os.path.relpath(file_path, self.lfs_repo_path)
            except ValueError:
                # If the path is not relative to the LFS repo, use the filename
                rel_path = os.path.basename(file_path)
        else:
            # It's already a relative path
            rel_path = file_path
        
        # Full path in the LFS repo
        full_path = os.path.join(self.lfs_repo_path, rel_path)
        
        if os.path.exists(full_path):
            if self.lfs_enabled:
                try:
                    # Pull the file content from Git LFS
                    subprocess.run(['git', 'lfs', 'pull', '--include', rel_path, '--exclude', ''], 
                                  cwd=self.lfs_repo_path, check=True)
                    logger.info(f"File pulled from Git LFS: {rel_path}")
                except Exception as e:
                    logger.error(f"Error pulling file from Git LFS: {str(e)}")
            
            return full_path
        else:
            # Check if it exists in the static folder as a fallback
            static_folder = None
            if has_app_context():
                static_folder = current_app.static_folder
            else:
                # Default static folder if outside app context
                static_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
                
            static_path = os.path.join(static_folder, rel_path)
            if os.path.exists(static_path):
                return static_path
            
            logger.error(f"File not found: {rel_path}")
            return None
    
    def delete_file(self, file_path):
        """
        Delete a file from Git LFS
        
        Args:
            file_path: The relative path to the file in the LFS repo
            
        Returns:
            bool: Whether the deletion was successful
        """
        # Check if it's a full path or relative path
        if os.path.isabs(file_path):
            try:
                rel_path = os.path.relpath(file_path, self.lfs_repo_path)
            except ValueError:
                # If the path is not relative to the LFS repo, use the filename
                rel_path = os.path.basename(file_path)
        else:
            # It's already a relative path
            rel_path = file_path
        
        # Full path in the LFS repo
        full_path = os.path.join(self.lfs_repo_path, rel_path)
        
        try:
            if os.path.exists(full_path):
                if self.lfs_enabled:
                    # Remove file from Git LFS
                    subprocess.run(['git', 'rm', '-f', full_path], cwd=self.lfs_repo_path, check=True)
                    
                    # Commit the deletion
                    commit_message = f"Remove {os.path.basename(full_path)}"
                    subprocess.run(['git', 'commit', '-m', commit_message], cwd=self.lfs_repo_path, check=True)
                    
                    logger.info(f"File removed from Git LFS: {rel_path}")
                else:
                    # Just delete the file if Git LFS is not enabled
                    os.remove(full_path)
                    logger.info(f"File deleted: {full_path}")
                
                return True
            else:
                # Check if it exists in the static folder as a fallback
                static_folder = None
                if has_app_context():
                    static_folder = current_app.static_folder
                else:
                    # Default static folder if outside app context
                    static_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
                    
                static_path = os.path.join(static_folder, rel_path)
                if os.path.exists(static_path):
                    os.remove(static_path)
                    logger.info(f"File deleted from static folder: {static_path}")
                    return True
                
                logger.warning(f"File not found for deletion: {rel_path}")
                return False
        except Exception as e:
            logger.error(f"Error deleting file: {str(e)}")
            return False
    
    def get_file_url(self, file_path):
        """
        Get a URL for a file
        
        Args:
            file_path: The relative path to the file in the LFS repo
            
        Returns:
            str: URL to access the file
        """
        # Check if it's a full path or relative path
        if os.path.isabs(file_path):
            try:
                rel_path = os.path.relpath(file_path, self.lfs_repo_path)
            except ValueError:
                # If the path is not relative to the LFS repo, check if it's in static folder
                static_folder = None
                if has_app_context():
                    static_folder = current_app.static_folder
                else:
                    # Default static folder if outside app context
                    static_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
                    
                if file_path.startswith(static_folder):
                    rel_path = os.path.relpath(file_path, static_folder)
                    if has_app_context():
                        return url_for('static', filename=rel_path)
                    else:
                        return f"/static/{rel_path}"
                else:
                    # Use the filename
                    rel_path = os.path.basename(file_path)
        else:
            # It's already a relative path
            rel_path = file_path
        
        # Check if the file exists in the static folder
        static_folder = None
        if has_app_context():
            static_folder = current_app.static_folder
        else:
            # Default static folder if outside app context
            static_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
            
        static_path = os.path.join(static_folder, rel_path)
        if os.path.exists(static_path):
            if has_app_context():
                return url_for('static', filename=rel_path)
            else:
                return f"/static/{rel_path}"
        
        # If the file exists in the LFS repo, copy it to the static folder to make it accessible
        full_path = os.path.join(self.lfs_repo_path, rel_path)
        if os.path.exists(full_path):
            try:
                # Create directory structure in static folder
                static_dir = os.path.dirname(static_path)
                os.makedirs(static_dir, exist_ok=True)
                
                # Copy file to static folder
                shutil.copy(full_path, static_path)
                
                if has_app_context():
                    return url_for('static', filename=rel_path)
                else:
                    return f"/static/{rel_path}"
            except Exception as e:
                logger.error(f"Error copying file to static folder: {str(e)}")
        
        logger.warning(f"Could not generate URL for: {file_path}")
        return None

# Create a singleton instance
storage_manager = GitLFSStorageManager()