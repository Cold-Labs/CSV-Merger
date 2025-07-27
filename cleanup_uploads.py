#!/usr/bin/env python3
"""
Upload Cleanup Utility
Removes files and folders in uploads/ directory older than 24 hours
"""

import os
import time
import shutil
from datetime import datetime, timedelta
from pathlib import Path

class UploadCleanup:
    def __init__(self, uploads_dir="uploads", max_age_hours=24):
        """
        Initialize cleanup utility
        
        Args:
            uploads_dir: Directory to clean up
            max_age_hours: Files older than this will be deleted
        """
        self.uploads_dir = Path(uploads_dir)
        self.max_age_hours = max_age_hours
        self.cutoff_time = time.time() - (max_age_hours * 3600)
        
    def should_delete(self, path):
        """Check if a file/folder should be deleted based on age"""
        try:
            # Get the modification time (most recent of creation/modification)
            stat = path.stat()
            file_time = max(stat.st_mtime, stat.st_ctime)
            
            # Delete if older than cutoff
            return file_time < self.cutoff_time
        except OSError:
            # If we can't stat the file, skip it
            return False
    
    def format_size(self, size_bytes):
        """Format file size in human readable format"""
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f} {size_names[i]}"
    
    def get_folder_size(self, folder_path):
        """Calculate total size of a folder"""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(folder_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(filepath)
                    except OSError:
                        pass
        except OSError:
            pass
        return total_size
    
    def clean_uploads(self, dry_run=False):
        """
        Clean up old uploads
        
        Args:
            dry_run: If True, only show what would be deleted without actually deleting
            
        Returns:
            dict: Statistics about the cleanup
        """
        if not self.uploads_dir.exists():
            print(f"❌ Upload directory {self.uploads_dir} does not exist")
            return {"error": "Directory not found"}
        
        print(f"🧹 Cleaning uploads older than {self.max_age_hours} hours...")
        print(f"📂 Scanning: {self.uploads_dir.absolute()}")
        print(f"⏰ Cutoff time: {datetime.fromtimestamp(self.cutoff_time)}")
        
        stats = {
            "folders_deleted": 0,
            "files_deleted": 0,
            "total_size_freed": 0,
            "errors": 0,
            "skipped": 0
        }
        
        # Get all items in uploads directory
        try:
            items = list(self.uploads_dir.iterdir())
        except OSError as e:
            print(f"❌ Error reading uploads directory: {e}")
            return {"error": str(e)}
        
        print(f"📁 Found {len(items)} items to check")
        
        for item in items:
            try:
                # Skip .DS_Store and other hidden files at root level
                if item.name.startswith('.'):
                    stats["skipped"] += 1
                    continue
                
                if self.should_delete(item):
                    # Calculate size before deletion
                    if item.is_dir():
                        size = self.get_folder_size(item)
                        item_type = "📁"
                    else:
                        size = item.stat().st_size
                        item_type = "📄"
                    
                    age_hours = (time.time() - item.stat().st_mtime) / 3600
                    
                    print(f"{item_type} {item.name} ({self.format_size(size)}, {age_hours:.1f}h old)")
                    
                    if not dry_run:
                        if item.is_dir():
                            shutil.rmtree(item)
                            stats["folders_deleted"] += 1
                        else:
                            item.unlink()
                            stats["files_deleted"] += 1
                        
                        stats["total_size_freed"] += size
                        print(f"  ✅ Deleted")
                    else:
                        print(f"  🔍 Would delete (dry run)")
                        if item.is_dir():
                            stats["folders_deleted"] += 1
                        else:
                            stats["files_deleted"] += 1
                        stats["total_size_freed"] += size
                else:
                    # Item is not old enough to delete
                    age_hours = (time.time() - item.stat().st_mtime) / 3600
                    print(f"⏩ Keeping {item.name} ({age_hours:.1f}h old)")
                    stats["skipped"] += 1
                    
            except Exception as e:
                print(f"❌ Error processing {item}: {e}")
                stats["errors"] += 1
        
        # Print summary
        print(f"\n📊 Cleanup Summary:")
        print(f"   📁 Folders {'would be ' if dry_run else ''}deleted: {stats['folders_deleted']}")
        print(f"   📄 Files {'would be ' if dry_run else ''}deleted: {stats['files_deleted']}")
        print(f"   💾 Space {'would be ' if dry_run else ''}freed: {self.format_size(stats['total_size_freed'])}")
        print(f"   ⏩ Items skipped: {stats['skipped']}")
        print(f"   ❌ Errors: {stats['errors']}")
        
        return stats

def main():
    """Main function for command line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Clean up old upload files")
    parser.add_argument("--dry-run", action="store_true", 
                       help="Show what would be deleted without actually deleting")
    parser.add_argument("--max-age", type=int, default=24,
                       help="Maximum age in hours (default: 24)")
    parser.add_argument("--uploads-dir", default="uploads",
                       help="Upload directory to clean (default: uploads)")
    
    args = parser.parse_args()
    
    cleanup = UploadCleanup(args.uploads_dir, args.max_age)
    stats = cleanup.clean_uploads(dry_run=args.dry_run)
    
    if "error" in stats:
        print(f"❌ Cleanup failed: {stats['error']}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main()) 