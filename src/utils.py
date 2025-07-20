import pandas as pd
import os
from typing import Dict, List

def create_test_csv_files(session_id: str) -> List[str]:
    """Create sample CSV files for testing the processor"""
    
    session_dir = f"uploads/{session_id}"
    os.makedirs(session_dir, exist_ok=True)
    
    # Sample Company CSV 1 - Clean format
    company_data_1 = pd.DataFrame({
        'Company Name': ['Acme Corp', 'Tech Solutions Ltd', 'Global Industries'],
        'Website': ['https://www.acme.com', 'techsolutions.net', 'http://global-industries.com/'],
        'Industry': ['Manufacturing', 'Technology', 'Finance'],
        'Employee Count': ['500-1000', '50-100', '1000+'],
        'Location': ['New York, NY', 'San Francisco, CA', 'London, UK']
    })
    
    # Sample Company CSV 2 - Messy headers and duplicate data
    company_data_2 = pd.DataFrame({
        'company_name': ['ACME CORP', 'StartupXYZ Inc', 'Global Industries'],  # Duplicate: Global Industries
        'company_domain': ['acme.com', 'www.startupxyz.io', 'global-industries.com'],
        'business_type': ['Manufacturing', 'SaaS', 'Financial Services'],
        'staff_size': ['750', '25', '2000'],  # More complete data for Global Industries
        'headquarters': ['New York', 'Austin, TX', 'London']
    })
    
    # Sample People CSV 1
    people_data_1 = pd.DataFrame({
        'First Name': ['John', 'Sarah', 'Mike'],
        'Last Name': ['Smith', 'Johnson', 'Brown'],
        'Job Title': ['CEO', 'CTO', 'Sales Manager'], 
        'Company': ['Acme Corp', 'Tech Solutions', 'StartupXYZ'],
        'Email': ['john@acme.com', 'sarah@techsolutions.net', 'mike@startupxyz.io'],
        'LinkedIn': ['linkedin.com/in/johnsmith', '', 'linkedin.com/in/mikebrown']
    })
    
    # Sample People CSV 2 - Different headers, some duplicates
    people_data_2 = pd.DataFrame({
        'fname': ['John', 'Alice', 'Mike'],  # Duplicate: John and Mike
        'lname': ['Smith', 'Davis', 'Brown'],
        'position': ['Chief Executive Officer', 'Marketing Director', 'VP Sales'],  # More complete data
        'employer': ['Acme Corp', 'Global Industries', 'StartupXYZ'],
        'person_email': ['j.smith@acme.com', 'alice@global-industries.com', 'm.brown@startupxyz.io'],
        'linkedin_profile': ['https://linkedin.com/in/johnsmith', 'linkedin.com/in/alicedavis', '']
    })
    
    # Save test files
    file_paths = []
    
    company_file_1 = os.path.join(session_dir, 'companies_clean.csv')
    company_data_1.to_csv(company_file_1, index=False)
    file_paths.append(company_file_1)
    
    company_file_2 = os.path.join(session_dir, 'companies_messy.csv')
    company_data_2.to_csv(company_file_2, index=False)
    file_paths.append(company_file_2)
    
    people_file_1 = os.path.join(session_dir, 'people_clean.csv')
    people_data_1.to_csv(people_file_1, index=False)
    file_paths.append(people_file_1)
    
    people_file_2 = os.path.join(session_dir, 'people_messy.csv')
    people_data_2.to_csv(people_file_2, index=False)
    file_paths.append(people_file_2)
    
    return file_paths

def format_bytes(bytes_value: int) -> str:
    """Format bytes into human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_value < 1024:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024
    return f"{bytes_value:.1f} TB"

def validate_session_id(session_id: str) -> bool:
    """Validate session ID format"""
    import re
    # UUID format validation
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    return bool(re.match(uuid_pattern, session_id, re.IGNORECASE))

def clean_filename(filename: str) -> str:
    """Clean filename for safe storage"""
    import re
    # Remove or replace invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Limit length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255-len(ext)] + ext
    return filename

def get_file_info(file_path: str) -> Dict:
    """Get file information"""
    try:
        stat = os.stat(file_path)
        return {
            'size_bytes': stat.st_size,
            'size_formatted': format_bytes(stat.st_size),
            'created': stat.st_ctime,
            'modified': stat.st_mtime
        }
    except (OSError, FileNotFoundError):
        return {
            'size_bytes': 0,
            'size_formatted': '0 B',
            'created': 0,
            'modified': 0
        } 