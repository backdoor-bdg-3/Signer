import os
import subprocess
import logging
import tempfile
import shutil
import uuid
import io
import glob
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import current_app, url_for, has_app_context

logger = logging.getLogger(__name__)

class GitLFSStorageManager:
    """
    Handles file storage operations using Git LFS for large files
    """
    
    def __init__(self):
        # Check if Git LFS is installed and properly configured
        self.lfs_installed = self._check_git_lfs_installed()
        
        # Get the persistent storage directory (default to /data/lfs if in production)
        self.storage_base_dir = os.environ.get('LFS_STORAGE_PATH', '/data/lfs')
        if os.environ.get('RENDER', False) and self.storage_base_dir == '/tmp/lfs_storage':
            # Override if we're on Render and using the default temp path
            self.storage_base_dir = '/data/lfs'
        
        # Ensure storage directory exists
        os.makedirs(self.storage_base_dir, exist_ok=True)
        
        # Get the main project directory (going up from the utils folder)
        self.project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        
        # Initialize LFS if needed
        if self.lfs_installed:
            self._init_git_lfs()
            
        logger.info(f"Git LFS Storage Manager initialized. Storage dir: {self.storage_base_dir}")
        logger.info(f"Git LFS Installed: {self.lfs_installed}")
    
    def _check_git_lfs_installed(self):
        """Check if Git LFS is installed and working properly"""
        try:
            # Check Git LFS version
            result = subprocess.run(['git', 'lfs', 'version'], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE, 
                                   text=True)
            
            if result.returncode != 0:
                logger.warning("Git LFS is not installed or not working properly")
                return False
                
            logger.info(f"Git LFS is installed: {result.stdout.strip()}")
            
            # Check if Git LFS is initialized in the repository
            # Try to find the Git root directory
            try:
                root_dir = subprocess.run(
                    ['git', 'rev-parse', '--show-toplevel'],
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    text=True,
                    check=True
                ).stdout.strip()
                
                # Check if .gitattributes exists and has LFS configurations
                gitattributes_path = os.path.join(root_dir, '.gitattributes')
                if os.path.exists(gitattributes_path):
                    with open(gitattributes_path, 'r') as f:
                        content = f.read()
                        if 'filter=lfs' in content:
                            return True
                        else:
                            logger.warning("Git LFS not properly configured in .gitattributes")
                else:
                    logger.warning(".gitattributes file not found")
            except subprocess.CalledProcessError:
                logger.warning("Not in a Git repository")
                
            return False
            
        except Exception as e:
            logger.error(f"Error checking Git LFS: {str(e)}")
            return False
    
    def _init_git_lfs(self):
        """Initialize Git LFS for the project"""
        try:
            # Check if we're in a git repository
            try:
                subprocess.run(
                    ['git', 'rev-parse', '--is-inside-work-tree'],
                    cwd=self.project_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True
                )
            except subprocess.CalledProcessError:
                logger.warning(f"Not in a Git repository at {self.project_dir}")
                return
            
            # Run git lfs install to ensure Git LFS hooks are set up
            subprocess.run(
                ['git', 'lfs', 'install'], 
                cwd=self.project_dir,
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                check=True
            )
            
            # Pull any existing LFS files
            subprocess.run(
                ['git', 'lfs', 'pull'],
                cwd=self.project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            logger.info("Git LFS initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing Git LFS: {str(e)}")
    
    def save_file(self, file_obj, directory, filename=None):
        """
        Save a file using Git LFS
        
        Args:
            file_obj: The file object to save
            directory: The directory to save the file to (relative to storage base)
            filename: Optional filename, if not provided will use the original filename
            
        Returns:
            tuple: (success, filepath)
        """
        try:
            # Generate a unique filename if none provided
            if filename is None:
                if hasattr(file_obj, 'filename'):
                    filename = secure_filename(file_obj.filename)
                else:
                    filename = f"file_{str(uuid.uuid4())[:8]}"
            
            # Add unique ID to avoid filename collisions
            unique_id = str(uuid.uuid4())[:8]
            filename = f"{unique_id}_{filename}"
            
            # Create the storage directory
            storage_dir = os.path.join(self.storage_base_dir, directory)
            os.makedirs(storage_dir, exist_ok=True)
            
            # Full path to save the file
            filepath = os.path.join(storage_dir, filename)
            
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
            
            # If we're in a git repository with LFS enabled, try to add the file to LFS
            if self.lfs_installed:
                # Check if file is in the git repository
                try:
                    repo_dir = self._copy_to_git_repo(filepath, directory, filename)
                    if repo_dir:
                        logger.info(f"File copied to git repository at {repo_dir}")
                except Exception as e:
                    logger.warning(f"Could not copy to git repository: {str(e)}")
            
            # Return the relative path within the storage base
            rel_path = os.path.join(directory, filename)
            return True, rel_path
            
        except Exception as e:
            logger.error(f"Error saving file: {str(e)}")
            return False, str(e)
    
    def _copy_to_git_repo(self, source_path, directory, filename):
        """
        Copy a file to the git repository and add it to Git LFS
        
        Args:
            source_path: Path to the source file
            directory: Relative directory path where the file should be placed
            filename: Filename
            
        Returns:
            str: Repository path where file was copied, or None if failed
        """
        try:
            # Determine the target path in the git repository
            repo_dir = None
            
            # Try to find the static folder in the git repository
            static_folder = None
            if has_app_context():
                static_folder = current_app.static_folder
            else:
                # Default static folder if outside app context
                static_folder = os.path.join(self.project_dir, 'app', 'static')
                
            repo_dir = os.path.join(static_folder, directory)
            os.makedirs(repo_dir, exist_ok=True)
            
            target_path = os.path.join(repo_dir, filename)
            
            # Copy the file
            shutil.copy(source_path, target_path)
            
            # Check if the extension is tracked by Git LFS
            file_ext = os.path.splitext(filename)[1].lower()
            
            # Don't try to add to git if this is not likely a git repository path
            if not os.path.exists(os.path.join(self.project_dir, '.git')):
                return target_path
                
            # Try to add the file to git
            try:
                # Check if this extension should be tracked by LFS
                attrs_check = subprocess.run(
                    ['git', 'check-attr', 'filter', target_path],
                    cwd=self.project_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                # Only add to git if we're in a repo and the file should be tracked
                if 'lfs' in attrs_check.stdout:
                    subprocess.run(
                        ['git', 'add', target_path],
                        cwd=self.project_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    logger.info(f"File added to Git LFS: {target_path}")
            except Exception as git_err:
                logger.warning(f"Could not add file to git: {str(git_err)}")
                
            return target_path
                
        except Exception as e:
            logger.error(f"Error copying file to git repo: {str(e)}")
            return None
    
    def get_file(self, file_path):
        """
        Get a file from storage
        
        Args:
            file_path: The relative path to the file in the storage base
            
        Returns:
            str: Path to the file
        """
        # If it's already a full path and exists, return it
        if os.path.isabs(file_path) and os.path.exists(file_path):
            return file_path
            
        # Try multiple possible locations for the file
        possible_paths = []
        
        # 1. Storage base dir
        possible_paths.append(os.path.join(self.storage_base_dir, file_path))
        
        # 2. Static folder
        static_folder = None
        if has_app_context():
            static_folder = current_app.static_folder
            possible_paths.append(os.path.join(static_folder, file_path))
        else:
            # Default static folder if outside app context
            static_folder = os.path.join(self.project_dir, 'app', 'static')
            possible_paths.append(os.path.join(static_folder, file_path))
        
        # 3. Look for files with the same base name (in case of unique ID prefixes)
        basename = os.path.basename(file_path)
        dir_path = os.path.dirname(file_path)
        
        # 3.1 In the storage base dir
        storage_dir = os.path.join(self.storage_base_dir, dir_path)
        if os.path.isdir(storage_dir):
            for f in os.listdir(storage_dir):
                if basename in f:
                    possible_paths.append(os.path.join(storage_dir, f))
        
        # 3.2 In the static folder
        static_dir = os.path.join(static_folder, dir_path)
        if os.path.isdir(static_dir):
            for f in os.listdir(static_dir):
                if basename in f:
                    possible_paths.append(os.path.join(static_dir, f))
        
        # Check all possible paths
        for path in possible_paths:
            if os.path.exists(path):
                # If we're using Git LFS, make sure the content is pulled
                if self.lfs_installed and path.startswith(self.project_dir):
                    try:
                        rel_path = os.path.relpath(path, self.project_dir)
                        # Check if this file is tracked by LFS
                        attrs_check = subprocess.run(
                            ['git', 'check-attr', 'filter', rel_path],
                            cwd=self.project_dir,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True
                        )
                        
                        if 'lfs' in attrs_check.stdout:
                            # Pull the file content from Git LFS
                            subprocess.run(
                                ['git', 'lfs', 'pull', '--include', rel_path, '--exclude', ''],
                                cwd=self.project_dir,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE
                            )
                            logger.info(f"File pulled from Git LFS: {rel_path}")
                    except Exception as e:
                        logger.warning(f"Error checking/pulling LFS file: {str(e)}")
                
                return path
        
        logger.error(f"File not found: {file_path}")
        return None
    
    def delete_file(self, file_path):
        """
        Delete a file from storage
        
        Args:
            file_path: The relative path to the file in the storage base
            
        Returns:
            bool: Whether the deletion was successful
        """
        # Get the actual file path
        actual_path = self.get_file(file_path)
        if not actual_path:
            logger.warning(f"File not found for deletion: {file_path}")
            return False
        
        try:
            # Delete the file
            os.remove(actual_path)
            logger.info(f"File deleted: {actual_path}")
            
            # If file is in git repository, try to remove it
            if self.lfs_installed and actual_path.startswith(self.project_dir):
                try:
                    rel_path = os.path.relpath(actual_path, self.project_dir)
                    subprocess.run(
                        ['git', 'rm', '-f', rel_path],
                        cwd=self.project_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    logger.info(f"File removed from git: {rel_path}")
                except Exception as e:
                    logger.warning(f"Error removing file from git: {str(e)}")
            
            return True
        except Exception as e:
            logger.error(f"Error deleting file: {str(e)}")
            return False
    
    def get_file_url(self, file_path):
        """
        Get a URL for a file
        
        Args:
            file_path: The relative path to the file in the storage
            
        Returns:
            str: URL to access the file
        """
        # Get the actual file path
        actual_path = self.get_file(file_path)
        if not actual_path:
            logger.warning(f"File not found for URL generation: {file_path}")
            return None
        
        # If it's in the static folder, we can generate a URL directly
        static_folder = None
        if has_app_context():
            static_folder = current_app.static_folder
        else:
            # Default static folder if outside app context
            static_folder = os.path.join(self.project_dir, 'app', 'static')
            
        if actual_path.startswith(static_folder):
            rel_path = os.path.relpath(actual_path, static_folder)
            if has_app_context():
                return url_for('static', filename=rel_path)
            else:
                return f"/static/{rel_path}"
        
        # If it's in the storage directory, copy it to the static folder
        try:
            # Get the relative path components
            basename = os.path.basename(actual_path)
            rel_dir = os.path.dirname(file_path)
            
            # Build the static path
            static_dir = os.path.join(static_folder, rel_dir)
            os.makedirs(static_dir, exist_ok=True)
            
            static_path = os.path.join(static_dir, basename)
            
            # Copy the file if it doesn't exist
            if not os.path.exists(static_path) or os.path.getsize(static_path) != os.path.getsize(actual_path):
                shutil.copy(actual_path, static_path)
            
            # Generate URL
            rel_static_path = os.path.join(rel_dir, basename)
            if has_app_context():
                return url_for('static', filename=rel_static_path)
            else:
                return f"/static/{rel_static_path}"
        except Exception as e:
            logger.error(f"Error generating URL for file: {str(e)}")
            return None

# Create a singleton instance
storage_manager = GitLFSStorageManager()