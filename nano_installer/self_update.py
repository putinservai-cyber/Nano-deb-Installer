import subprocess
import os
from PyQt5.QtWidgets import QMessageBox, QProgressDialog
from PyQt5.QtCore import QProcess, Qt

def check_for_updates(parent: QMessageBox):
    """
    Checks for updates by running 'git fetch' and comparing local/remote branches.
    Assumes the application is run from a Git repository root.
    """
    repo_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # /home/putinservai/Documents/nano

    try:
        # 1. Fetch latest changes
        fetch_result = subprocess.run(
            ['git', 'fetch'],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True
        )
        
        # 2. Check for differences
        try:
            diff_result = subprocess.run(
                ['git', 'rev-list', 'HEAD..@{u}', '--count'],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            updates_available = int(diff_result.stdout.strip()) > 0
        except subprocess.CalledProcessError as e:
            if "no such branch: 'HEAD..@{u}'" in e.stderr or "no such branch: 'HEAD..'" in e.stderr:
                QMessageBox.warning(parent, "Update Configuration Missing",
                                    "Cannot check for updates: The current Git branch does not have an upstream remote configured. "
                                    "Please configure the remote tracking branch (e.g., `git branch --set-upstream-to=origin/main`).")
                return
            raise # Re-raise other errors
        
        if updates_available:
            reply = QMessageBox.question(
                parent, 
                "Update Available", 
                "A new version is available. Do you want to update now? The application will restart after updating.",
                QMessageBox.Yes | QMessageBox.No, 
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                perform_update(parent, repo_path)
            else:
                QMessageBox.information(parent, "Update Cancelled", "Update postponed.")
        else:
            QMessageBox.information(parent, "No Updates", "The application is already up to date.")

    except subprocess.CalledProcessError as e:
        # This block now only catches errors from git fetch
        QMessageBox.critical(parent, "Update Error", f"Failed to check for updates (Git fetch error):\n{e.stderr}")
    except FileNotFoundError:
        QMessageBox.critical(parent, "Update Error", "Git command not found. Ensure Git is installed and accessible.")
    except Exception as e:
        QMessageBox.critical(parent, "Update Error", f"An unexpected error occurred during update check: {e}")


def perform_update(parent, repo_path):
    """Performs the git pull and restarts the application."""
    
    progress_dialog = QProgressDialog("Updating application...", "Cancel", 0, 0, parent)
    progress_dialog.setWindowModality(Qt.WindowModal)
    progress_dialog.setCancelButton(None) # Disable cancel button during critical operation
    progress_dialog.show()
    
    try:
        # 1. Pull changes
        progress_dialog.setLabelText("Pulling latest changes...")
        subprocess.run(
            ['git', 'pull'],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True
        )
        
        # 2. Restart application
        progress_dialog.setLabelText("Update complete. Restarting application...")
        QMessageBox.information(parent, "Success", "Application updated successfully. Restarting now.")
        
        # Get the command used to launch the current process
        # Note: This assumes the application was launched via a simple command like 'python3 nano-installer.py'
        # For robust restart, we use sys.executable and sys.argv from the main process.
        
        # We need to exit the current application and launch a new process.
        # Since we cannot access sys.executable/sys.argv directly here, we rely on the main module 
        # to handle the restart logic after this function returns.
        
        # For now, we just exit and rely on the user/system to restart it, or we signal the main app to handle it.
        # Since this is a helper script, we'll rely on the main app to handle the restart.
        
        # Signal main app to exit cleanly
        parent.close() # Close the main window, triggering application exit
        
    except subprocess.CalledProcessError as e:
        QMessageBox.critical(parent, "Update Failed", f"Failed to pull updates (Git error):\n{e.stderr}")
    except Exception as e:
        QMessageBox.critical(parent, "Update Failed", f"An unexpected error occurred during update: {e}")
    finally:
        progress_dialog.close()