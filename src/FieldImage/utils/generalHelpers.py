import os
import re

from datetime import datetime, timedelta

from .constants import GREEN, RESET


def validate_date(date_str):
    """Ensure the date is in YYYY-MM-DD format."""

    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    
def get_date_input():
    """Asks for dates of data collection and returns dates in an isoformat list."""

    while True:
        choice = input("For the dates of data collection, "
        f"would you like to enter a date {GREEN}range{RESET} or a {GREEN}list{RESET} of dates? (range/list): ").strip().lower()
        print()

        if choice == "range":
            start_date = validate_date(input("Enter the start date (YYYY-MM-DD): ").strip())
            end_date = validate_date(input("Enter the end date (YYYY-MM-DD): ").strip())
            print()

            if start_date and end_date and start_date <= end_date:
                # Generate a list of all dates within the range
                date_list = [(start_date + timedelta(days=i)).isoformat() for i in range((end_date - start_date).days + 1)]
                return date_list
            else:
                print("Invalid date range. Please try again. Enter 'exit' to quit.\n")

        elif choice == "list":
            dates = input("Enter a list of dates (comma-separated, YYYY-MM-DD): ").strip().split(",")
            print()
            date_list = [validate_date(date.strip()) for date in dates]
            
            if all(date_list):  # Ensure all dates are valid
                return [date.isoformat() for date in date_list]
            else:
                print("One or more dates were invalid. Please enter dates in YYYY-MM-DD format. Enter 'exit' to quit.\n")

        elif choice == "exit":
            exit()

        else:
            print("Invalid choice. Please enter 'range' or 'list' to continue, or enter 'exit' to quit.\n")

def get_list_input(prompt):
    """Ask for a list of items as input, ensuring at least one valid entry."""
    
    while True:  
        response = input(prompt + " ").strip()

        if response == "exit":
            exit()

        items = [item.strip() for item in response.split(",") if item.strip()]  # Clean input
        
        if items:
            return items
        else:
            print("Invalid input. Please enter at least one item. Enter 'exit' to quit. \n")

def print_directory_structure(directory, indent=""):
    # List all items in the current directory (this is from ChatGPT)
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.is_dir():
                # Print the directory with an indent and recurse
                print(f"{indent}├── {entry.name}")
                # Recurse into subdirectory
                print_directory_structure(entry.path, indent + "│   ")
            else:
                # Print the file
                print(f"{indent}├── {entry.name}")

def is_valid_date_format(date_folder):
    """Check if the folder name follows the YYYY-MM-DD format. ChatGPT"""
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_folder))