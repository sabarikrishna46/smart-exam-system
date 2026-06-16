"""
PDF Extractor Module
Extracts student data from PDF files and converts to structured format
"""

import pdfplumber
import re
from typing import List, Dict, Optional, Tuple
import io

class PDFStudentExtractor:
    """Extract student information from PDF documents"""
    
    def __init__(self, pdf_file):
        """
        Initialize extractor with PDF file
        
        Args:
            pdf_file: File object or path to PDF
        """
        self.pdf_file = pdf_file
        self.students = []
        
    def extract_text_from_pdf(self) -> str:
        """Extract all text from PDF"""
        text = ""
        try:
            with pdfplumber.open(self.pdf_file) as pdf:
                for page in pdf.pages:
                    text += page.extract_text() or ""
                    text += "\n"
        except Exception as e:
            raise Exception(f"Error reading PDF: {str(e)}")
        return text
    
    def extract_table_from_pdf(self) -> List[Dict]:
        """Extract tabular data from PDF"""
        students = []
        try:
            with pdfplumber.open(self.pdf_file) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            students.extend(self._parse_table(table))
        except Exception as e:
            raise Exception(f"Error extracting table from PDF: {str(e)}")
        return students
    
    def _parse_table(self, table: List[List]) -> List[Dict]:
        """Parse table data into student records"""
        students = []
        
        if not table or len(table) < 2:
            return students
        
        # First row is assumed to be headers
        headers = [str(h).strip().lower() if h else "" for h in table[0]]
        
        # Normalize header names for flexibility
        header_mapping = {
            'roll': 'roll_no',
            'roll no': 'roll_no',
            'roll_no': 'roll_no',
            'rollno': 'roll_no',
            'student id': 'roll_no',
            'id': 'roll_no',
            
            'name': 'name',
            'student name': 'name',
            'full name': 'name',
            
            'email': 'email',
            'student email': 'email',
            'e-mail': 'email',
            
            'dept': 'department',
            'department': 'department',
            'dept.': 'department',
            'course': 'department',
            
            'sem': 'semester',
            'semester': 'semester',
            'sem.': 'semester',
            'year': 'semester',
            
            'arrear': 'is_arrear',
            'is_arrear': 'is_arrear',
            'has arrear': 'is_arrear',
            'arrear status': 'is_arrear',
            
            'arrear sem': 'arrear_semester',
            'arrear_semester': 'arrear_semester',
            'arrear semester': 'arrear_semester',
            
            'exam code': 'arrear_exam_code',
            'exam_code': 'arrear_exam_code',
            'arrear exam': 'arrear_exam_code',
        }
        
        # Map headers
        normalized_headers = {}
        for i, header in enumerate(headers):
            if header in header_mapping:
                normalized_headers[i] = header_mapping[header]
            else:
                # Try to match partial strings
                for key, mapped_val in header_mapping.items():
                    if key in header or header in key:
                        normalized_headers[i] = mapped_val
                        break
        
        # Parse data rows
        for row in table[1:]:
            student = {}
            for col_idx, cell in enumerate(row):
                if col_idx in normalized_headers:
                    field_name = normalized_headers[col_idx]
                    cell_value = str(cell).strip() if cell else ""
                    
                    # Special handling for boolean fields
                    if field_name == 'is_arrear':
                        cell_value = self._parse_boolean(cell_value)
                    elif field_name in ['semester', 'arrear_semester']:
                        cell_value = self._extract_number(cell_value) or ""
                    
                    if cell_value:
                        student[field_name] = cell_value
            
            # Only add if we have at least roll_no and name
            if 'roll_no' in student or 'name' in student:
                students.append(student)
        
        return students
    
    def extract_text_format(self, pattern: Optional[str] = None) -> List[Dict]:
        """
        Extract student data from unstructured text using regex patterns
        
        Args:
            pattern: Optional custom regex pattern for matching student records
                    Default pattern looks for: Roll No: <value>, Name: <value>, etc.
        
        Returns:
            List of student dictionaries
        """
        text = self.extract_text_from_pdf()
        students = []
        
        if not pattern:
            # Default patterns to match various formats
            # Pattern 1: Roll: X Name: Y Email: Z ...
            pattern1 = r'(?:Roll\s*(?:No|No\.)?|ID|Student\s*ID)\s*[:=]?\s*(\S+)\s+(?:Name|Full\s*Name)\s*[:=]?\s*([^,\n]+?)(?:\s+Email|$)'
            
            # Try pattern 1
            matches = re.finditer(pattern1, text, re.IGNORECASE)
            for match in matches:
                student = {
                    'roll_no': match.group(1),
                    'name': match.group(2).strip()
                }
                students.append(student)
        else:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                student = match.groupdict()
                students.append(student)
        
        return students
    
    def _parse_boolean(self, value: str) -> str:
        """Parse boolean values to 0 or 1"""
        if value.lower() in ['yes', 'true', '1', 'y', 'arrear', 'has arrear']:
            return '1'
        elif value.lower() in ['no', 'false', '0', 'n', 'regular']:
            return '0'
        return value
    
    def _extract_number(self, value: str) -> Optional[int]:
        """Extract first number from string"""
        match = re.search(r'\d+', value)
        return int(match.group()) if match else None
    
    def validate_students(self, students: List[Dict]) -> Tuple[List[Dict], List[str]]:
        """
        Validate extracted student data
        
        Returns:
            Tuple of (valid_students, error_messages)
        """
        valid_students = []
        errors = []
        
        required_fields = ['roll_no', 'name', 'email', 'department', 'semester']
        
        for idx, student in enumerate(students, 1):
            row_errors = []
            
            # Check required fields
            for field in required_fields:
                if field not in student or not student[field]:
                    row_errors.append(f"Missing {field}")
            
            # Validate email format
            if 'email' in student:
                if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', student['email']):
                    row_errors.append(f"Invalid email format: {student['email']}")
            
            # Validate semester is numeric
            if 'semester' in student:
                try:
                    sem = int(student['semester'])
                    if sem < 1 or sem > 6:
                        row_errors.append(f"Semester must be between 1-6, got {sem}")
                except ValueError:
                    row_errors.append(f"Semester must be numeric, got {student['semester']}")
            
            # Validate arrear_semester if is_arrear is 1
            if student.get('is_arrear') == '1':
                if 'arrear_semester' not in student or not student['arrear_semester']:
                    row_errors.append("Arrear semester required when is_arrear=1")
                elif not student.get('arrear_exam_code'):
                    row_errors.append("Arrear exam code required when is_arrear=1")
            
            if row_errors:
                error_msg = f"Row {idx} ({student.get('roll_no', 'N/A')}): " + "; ".join(row_errors)
                errors.append(error_msg)
            else:
                valid_students.append(student)
        
        return valid_students, errors
    
    def extract_all(self) -> Tuple[List[Dict], List[str]]:
        """
        Extract and validate all student data from PDF
        
        Returns:
            Tuple of (valid_students, error_messages)
        """
        students = []
        errors = []
        
        try:
            # Try table extraction first
            students = self.extract_table_from_pdf()
            
            if not students:
                # Fall back to text extraction
                students = self.extract_text_format()
        except Exception as e:
            errors.append(f"Extraction error: {str(e)}")
        
        if not students:
            errors.append("No student data found in PDF. Ensure PDF contains a table or structured text.")
            return [], errors
        
        # Validate extracted data
        valid_students, validation_errors = self.validate_students(students)
        errors.extend(validation_errors)
        
        return valid_students, errors


def extract_students_from_pdf(pdf_file) -> Tuple[List[Dict], List[str]]:
    """
    Convenience function to extract students from PDF
    
    Args:
        pdf_file: File object or path to PDF
    
    Returns:
        Tuple of (students, errors)
    """
    extractor = PDFStudentExtractor(pdf_file)
    return extractor.extract_all()
