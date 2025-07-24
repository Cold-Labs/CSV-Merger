import os
import json
import logging
import shutil
from datetime import datetime
from typing import Dict, Any, Optional
# from watchdog.observers import Observer
# from watchdog.events import FileSystemEventHandler

from src.logging_config import setup_module_logger
from config.settings import Config  # Import the main Config class

logger = setup_module_logger(__name__)

# Disabled file watching functionality for production simplicity
# class ConfigFileHandler(FileSystemEventHandler):
#     """File system event handler for configuration file changes"""
#     
#     def __init__(self, config_manager):
#         self.config_manager = config_manager
#         
#     def on_modified(self, event):
#         if not event.is_directory and event.src_path.endswith('.json'):
#             logging.info(f"Configuration file modified: {event.src_path}")
#             self.config_manager.reload_mappings()

class ConfigManager:
    """Manages field mappings and configuration with hot-reload capability"""
    
    def __init__(self, config_file_path: str):
        self.config_file = config_file_path
        self.backup_dir = 'config/backup'
        self.mappings = {}
        self._ensure_backup_dir()
        self.load_field_mappings()
        self._setup_file_watcher()
    
    def get_n8n_webhook_url(self) -> str:
        """Get the n8n webhook URL from the main app config"""
        return Config.N8N_WEBHOOK_URL
    
    def _ensure_backup_dir(self):
        """Create backup directory if it doesn't exist"""
        os.makedirs(self.backup_dir, exist_ok=True)
    
    def load_field_mappings(self) -> Dict[str, Any]:
        """Load field mappings from JSON file"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.mappings = json.load(f)
            logging.info(f"Field mappings loaded from {self.config_file}")
            return self.mappings
        except FileNotFoundError:
            logging.error(f"Configuration file not found: {self.config_file}")
            raise
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON in configuration file: {e}")
            raise
    
    def reload_mappings(self):
        """Hot-reload field mappings"""
        try:
            old_mappings = self.mappings.copy()
            self.load_field_mappings()
            logging.info("Field mappings hot-reloaded successfully")
        except Exception as e:
            logging.error(f"Failed to reload mappings: {e}")
            self.mappings = old_mappings  # Restore previous mappings
    
    def update_field_mappings(self, new_mappings: Dict[str, Any]) -> bool:
        """Update field mappings with validation and hot-reload"""
        try:
            # Validate new mappings
            if not self.validate_mappings(new_mappings):
                return False
            
            # Create backup before updating
            self.backup_config()
            
            # Write new mappings
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(new_mappings, f, indent=2, ensure_ascii=False)
            
            # Update in-memory mappings
            self.mappings = new_mappings
            logging.info("Field mappings updated successfully")
            return True
            
        except Exception as e:
            logging.error(f"Failed to update field mappings: {e}")
            return False
    
    def validate_mappings(self, mappings: Dict[str, Any]) -> bool:
        """Validate mapping structure and content"""
        required_sections = ['company_mappings', 'people_mappings', 'data_cleaning_rules']
        
        # Check required sections exist
        for section in required_sections:
            if section not in mappings:
                logging.error(f"Missing required section: {section}")
                return False
        
        # Validate company mappings
        if not isinstance(mappings['company_mappings'], dict):
            logging.error("company_mappings must be a dictionary")
            return False
        
        # Validate people mappings
        if not isinstance(mappings['people_mappings'], dict):
            logging.error("people_mappings must be a dictionary")
            return False
        
        # Validate each mapping has a list of alternatives
        for section in ['company_mappings', 'people_mappings']:
            for field, alternatives in mappings[section].items():
                if not isinstance(alternatives, list):
                    logging.error(f"Mapping for {field} must be a list")
                    return False
                if not alternatives:
                    logging.error(f"Mapping for {field} cannot be empty")
                    return False
        
        # Validate data cleaning rules
        cleaning_rules = mappings['data_cleaning_rules']
        required_cleaning_keys = ['domain_prefixes_to_remove', 'domain_suffixes_to_remove']
        for key in required_cleaning_keys:
            if key not in cleaning_rules:
                logging.error(f"Missing required cleaning rule: {key}")
                return False
            if not isinstance(cleaning_rules[key], list):
                logging.error(f"{key} must be a list")
                return False
        
        logging.info("Mapping validation successful")
        return True
    
    def backup_config(self) -> str:
        """Create timestamped backup of current configuration"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"field_mappings_backup_{timestamp}.json"
        backup_path = os.path.join(self.backup_dir, backup_filename)
        
        try:
            shutil.copy2(self.config_file, backup_path)
            logging.info(f"Configuration backed up to {backup_path}")
            return backup_path
        except Exception as e:
            logging.error(f"Failed to create backup: {e}")
            raise
    
    def restore_config(self, backup_file: str) -> bool:
        """Restore configuration from backup"""
        try:
            # Validate backup file exists
            if not os.path.exists(backup_file):
                logging.error(f"Backup file not found: {backup_file}")
                return False
            
            # Validate backup file content
            with open(backup_file, 'r', encoding='utf-8') as f:
                backup_mappings = json.load(f)
            
            if not self.validate_mappings(backup_mappings):
                logging.error("Backup file contains invalid mappings")
                return False
            
            # Create backup of current config before restoring
            self.backup_config()
            
            # Restore from backup
            shutil.copy2(backup_file, self.config_file)
            self.load_field_mappings()
            
            logging.info(f"Configuration restored from {backup_file}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to restore configuration: {e}")
            return False
    
    def get_mapping_preview(self) -> Dict[str, Any]:
        """Get current mappings for UI display"""
        return {
            'company_fields': list(self.mappings.get('company_mappings', {}).keys()),
            'people_fields': list(self.mappings.get('people_mappings', {}).keys()),
            'total_company_mappings': len(self.mappings.get('company_mappings', {})),
            'total_people_mappings': len(self.mappings.get('people_mappings', {})),
            'cleaning_rules_count': len(self.mappings.get('data_cleaning_rules', {}))
        }
    
    def get_company_mappings(self) -> Dict[str, list]:
        """Get company field mappings"""
        return self.mappings.get('company_mappings', {})
    
    def get_people_mappings(self) -> Dict[str, list]:
        """Get people field mappings"""
        return self.mappings.get('people_mappings', {})
    
    def get_cleaning_rules(self) -> Dict[str, Any]:
        """Get data cleaning rules"""
        return self.mappings.get('data_cleaning_rules', {})
    
    def get_field_mappings(self) -> Dict[str, Any]:
        """Get current field mappings"""
        return self.mappings
    
    def get_last_modified(self) -> str:
        """Get last modified timestamp of config file"""
        try:
            stat = os.stat(self.config_file)
            return datetime.fromtimestamp(stat.st_mtime).isoformat()
        except Exception as e:
            logging.error(f"Failed to get last modified time: {e}")
            return None
    
    def validate_field_mappings(self, mappings: Dict[str, Any]) -> Dict[str, Any]:
        """Validate field mappings and return detailed results"""
        errors = []
        warnings = []
        
        try:
            # Check if mappings is a dictionary
            if not isinstance(mappings, dict):
                errors.append("Field mappings must be a dictionary")
                return {'valid': False, 'errors': errors, 'warnings': warnings}
            
            # Check required sections
            required_sections = ['company_mappings', 'people_mappings', 'data_cleaning_rules']
            for section in required_sections:
                if section not in mappings:
                    errors.append(f"Missing required section: {section}")
                elif not isinstance(mappings[section], dict):
                    errors.append(f"Section '{section}' must be a dictionary")
            
            # If basic structure is invalid, return early
            if errors:
                return {'valid': False, 'errors': errors, 'warnings': warnings}
            
            # Validate company mappings
            company_mappings = mappings.get('company_mappings', {})
            for field, alternatives in company_mappings.items():
                if not isinstance(alternatives, list):
                    errors.append(f"Company mapping for '{field}' must be a list")
                elif not alternatives:
                    warnings.append(f"Company mapping for '{field}' is empty")
                elif len(alternatives) > 20:
                    warnings.append(f"Company mapping for '{field}' has many alternatives ({len(alternatives)})")
            
            # Validate people mappings
            people_mappings = mappings.get('people_mappings', {})
            for field, alternatives in people_mappings.items():
                if not isinstance(alternatives, list):
                    errors.append(f"People mapping for '{field}' must be a list")
                elif not alternatives:
                    warnings.append(f"People mapping for '{field}' is empty")
                elif len(alternatives) > 20:
                    warnings.append(f"People mapping for '{field}' has many alternatives ({len(alternatives)})")
            
            # Validate data cleaning rules
            cleaning_rules = mappings.get('data_cleaning_rules', {})
            required_cleaning_keys = ['domain_prefixes_to_remove', 'domain_suffixes_to_remove']
            for key in required_cleaning_keys:
                if key not in cleaning_rules:
                    errors.append(f"Missing required cleaning rule: {key}")
                elif not isinstance(cleaning_rules[key], list):
                    errors.append(f"Cleaning rule '{key}' must be a list")
            
            # Check for common field name issues
            all_fields = set(company_mappings.keys()) | set(people_mappings.keys())
            for field in all_fields:
                if not field.strip():
                    errors.append("Field names cannot be empty or whitespace only")
                elif len(field) > 100:
                    warnings.append(f"Field name '{field}' is very long ({len(field)} characters)")
            
            return {
                'valid': len(errors) == 0,
                'errors': errors,
                'warnings': warnings
            }
            
        except Exception as e:
            errors.append(f"Validation error: {str(e)}")
            return {'valid': False, 'errors': errors, 'warnings': warnings}
    
    def reset_to_defaults(self) -> bool:
        """Reset field mappings to default configuration"""
        try:
            # Create backup before reset
            self.backup_config()
            
            # Default field mappings
            default_mappings = {
                "company_mappings": {
                    "company_name": ["company", "organization", "company_name", "org", "business_name"],
                    "website": ["website", "url", "domain", "web", "site"],
                    "industry": ["industry", "sector", "business_type", "category"],
                    "size": ["size", "company_size", "employees", "headcount"],
                    "location": ["location", "address", "city", "country", "headquarters"]
                },
                "people_mappings": {
                    "first_name": ["first_name", "fname", "given_name", "first"],
                    "last_name": ["last_name", "lname", "surname", "family_name", "last"],
                    "full_name": ["name", "full_name", "contact_name", "person"],
                    "email": ["email", "email_address", "e_mail", "contact_email"],
                    "title": ["title", "job_title", "position", "role"],
                    "department": ["department", "dept", "division", "team"],
                    "phone": ["phone", "telephone", "mobile", "phone_number"]
                },
                "data_cleaning_rules": {
                    "domain_prefixes_to_remove": ["http://", "https://", "www.", "mail."],
                    "domain_suffixes_to_remove": ["/", "?", "#"],
                    "normalize_domains": True,
                    "remove_duplicates": True,
                    "trim_whitespace": True
                }
            }
            
            # Save default mappings
            return self.update_field_mappings(default_mappings)
            
        except Exception as e:
            logging.error(f"Failed to reset to defaults: {e}")
            return False
    
    def create_backup(self) -> Optional[Dict[str, Any]]:
        """Create a backup and return backup information"""
        try:
            backup_path = self.backup_config()
            
            # Get backup file info
            stat = os.stat(backup_path)
            
            return {
                'filename': os.path.basename(backup_path),
                'path': backup_path,
                'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                'size_bytes': stat.st_size,
                'size_mb': round(stat.st_size / 1024 / 1024, 2)
            }
            
        except Exception as e:
            logging.error(f"Failed to create backup: {e}")
            return None
    
    def list_backups(self) -> list:
        """List available backup files"""
        try:
            backup_files = []
            for filename in os.listdir(self.backup_dir):
                if filename.startswith('field_mappings_backup_') and filename.endswith('.json'):
                    file_path = os.path.join(self.backup_dir, filename)
                    file_stat = os.stat(file_path)
                    backup_files.append({
                        'filename': filename,
                        'path': file_path,
                        'created_at': datetime.fromtimestamp(file_stat.st_ctime).isoformat(),
                        'size_bytes': file_stat.st_size,
                        'size_mb': round(file_stat.st_size / 1024 / 1024, 2)
                    })
            
            # Sort by creation date (newest first)
            backup_files.sort(key=lambda x: x['created_at'], reverse=True)
            return backup_files
            
        except Exception as e:
            logging.error(f"Failed to list backups: {e}")
            return []
    
    def _setup_file_watcher(self):
        """Setup file system watcher for hot-reload"""
        try:
            # File watcher disabled in production to avoid watchdog dependency
            logging.info("File watcher disabled for production deployment")
            return
            
            # This code requires watchdog dependency - disabled for production
            # self.observer = Observer()
            # event_handler = ConfigFileHandler(self)
            # 
            # # Watch the config directory
            # config_dir = os.path.dirname(self.config_file)
            # self.observer.schedule(event_handler, config_dir, recursive=False)
            # self.observer.start()
            # 
            # logging.info(f"File watcher setup for {config_dir}")
        except Exception as e:
            logging.error(f"Failed to setup file watcher: {e}")
    
    def stop_file_watcher(self):
        """Stop the file system watcher"""
        try:
            # File watcher disabled in production - no observer to stop
            if hasattr(self, 'observer') and self.observer:
                self.observer.stop()
                self.observer.join()
                logging.info("File watcher stopped")
            else:
                logging.debug("No file watcher to stop (disabled in production)")
        except Exception as e:
            logging.error(f"Error stopping file watcher: {e}")
    
    def __del__(self):
        """Cleanup when object is destroyed"""
        self.stop_file_watcher() 