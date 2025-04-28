import os
import time
import logging
import subprocess
import shutil
import threading
import queue
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('worker.log')
    ]
)

logger = logging.getLogger('worker')

class SigningHandler(FileSystemEventHandler):
    def __init__(self, upload_dir, signed_dir, max_concurrent=2):
        self.upload_dir = upload_dir
        self.signed_dir = signed_dir
        self.processing = set()
        self.job_queue = queue.Queue()
        self.max_concurrent = int(os.environ.get('MAX_CONCURRENT_TASKS', max_concurrent))
        self.worker_threads = []
        
        # Start worker threads
        for i in range(self.max_concurrent):
            thread = threading.Thread(target=self.worker_thread, daemon=True)
            thread.start()
            self.worker_threads.append(thread)
            logger.info(f"Started worker thread {i+1}")
        
    def worker_thread(self):
        while True:
            session_id = self.job_queue.get()
            try:
                self.process_signing_job(session_id)
            except Exception as e:
                logger.exception(f"Error in worker thread processing job {session_id}: {str(e)}")
            finally:
                self.job_queue.task_done()
                if session_id in self.processing:
                    self.processing.remove(session_id)
        
    def on_created(self, event):
        if event.is_directory and event.src_path.endswith('_to_sign'):
            session_id = os.path.basename(event.src_path).replace('_to_sign', '')
            if session_id not in self.processing:
                self.processing.add(session_id)
                logger.info(f"New signing job detected: {session_id}")
                self.job_queue.put(session_id)
    
    def process_signing_job(self, session_id):
        try:
            job_dir = os.path.join(self.upload_dir, f"{session_id}_to_sign")
            
            # Read job configuration
            config_path = os.path.join(job_dir, 'config.txt')
            if not os.path.exists(config_path):
                logger.error(f"No config file found for job {session_id}")
                return
            
            with open(config_path, 'r') as f:
                lines = f.readlines()
                config = {}
                for line in lines:
                    if ':' in line:
                        key, value = line.strip().split(':', 1)
                        config[key.strip()] = value.strip()
            
            # Get file paths
            ipa_path = os.path.join(job_dir, config.get('ipa_file', ''))
            p12_path = os.path.join(job_dir, config.get('p12_file', ''))
            provision_path = os.path.join(job_dir, config.get('provision_file', ''))
            p12_password = config.get('p12_password', '')
            
            if not all([os.path.exists(ipa_path), os.path.exists(p12_path), os.path.exists(provision_path)]):
                logger.error(f"Missing required files for job {session_id}")
                return
            
            # Output path for signed IPA
            output_filename = f"signed_{os.path.basename(ipa_path)}"
            output_path = os.path.join(self.signed_dir, output_filename)
            
            # Execute zsign command
            cmd = [
                'zsign', 
                '-k', p12_path, 
                '-p', p12_password, 
                '-m', provision_path, 
                '-o', output_path, 
                '-z', '9', 
                ipa_path
            ]
            
            logger.info(f"Starting signing process for job {session_id}")
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                logger.error(f"Error signing app for job {session_id}: {stderr}")
                with open(os.path.join(job_dir, 'error.log'), 'w') as f:
                    f.write(stderr)
            else:
                logger.info(f"Successfully signed app for job {session_id}")
                with open(os.path.join(job_dir, 'success.log'), 'w') as f:
                    f.write(stdout)
                    f.write(f"\nOutput file: {output_filename}")
            
            # Create completion marker
            with open(os.path.join(job_dir, 'completed'), 'w') as f:
                f.write('done')
                
        except Exception as e:
            logger.exception(f"Error processing job {session_id}: {str(e)}")
        finally:
            if session_id in self.processing:
                self.processing.remove(session_id)

def main():
    # Get directories from environment or use defaults
    app_dir = os.environ.get('APP_DIR', os.path.dirname(os.path.abspath(__file__)))
    upload_dir = os.environ.get('UPLOAD_DIR', os.path.join(app_dir, 'app', 'static', 'uploads'))
    signed_dir = os.environ.get('SIGNED_DIR', os.path.join(app_dir, 'app', 'static', 'signed'))
    
    # Ensure directories exist
    os.makedirs(upload_dir, exist_ok=True)
    os.makedirs(signed_dir, exist_ok=True)
    
    # Get max concurrent tasks from environment
    max_concurrent = int(os.environ.get('MAX_CONCURRENT_TASKS', 2))
    
    logger.info(f"Starting worker with {max_concurrent} concurrent tasks. Monitoring directory: {upload_dir}")
    
    # Process any existing jobs that might have been left from a previous run
    for item in os.listdir(upload_dir):
        if item.endswith('_to_sign') and os.path.isdir(os.path.join(upload_dir, item)):
            job_dir = os.path.join(upload_dir, item)
            if not os.path.exists(os.path.join(job_dir, 'completed')):
                logger.info(f"Found existing job: {item}")
                # Create a new event to trigger processing
                event = type('Event', (), {'is_directory': True, 'src_path': job_dir})
                event_handler = SigningHandler(upload_dir, signed_dir, max_concurrent)
                event_handler.on_created(event)
    
    # Set up event handler and observer
    event_handler = SigningHandler(upload_dir, signed_dir, max_concurrent)
    observer = Observer()
    observer.schedule(event_handler, upload_dir, recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    
    logger.info("Shutting down worker...")
    observer.join()

if __name__ == "__main__":
    main()