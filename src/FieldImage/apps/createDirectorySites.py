import yaml
import os
import sys

from pathlib import Path

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

if project_root not in sys.path:
    sys.path.append(project_root)

from utils.generalHelpers import get_list_input, get_date_input, print_directory_structure
from utils.constants import GREEN, RESET

def get_sites(date_list):
    """Asks for the sites where data will be collected for each date, returns a dictionary with a list of sites for each date."""

    date_site_dict = {date: None for date in date_list}

    for date in date_list:
        sites = get_list_input(f"Enter a comma-separated {GREEN}list of sites{RESET} you will be visiting on {GREEN}{date}{RESET} "
        "(e.g., site_1, site_2, site_3): ")
        date_site_dict[date] = sites

    print()

    return date_site_dict


def get_site_information(date_site_dict, date_list, empty=False):
    """Asks for additional information regarding each site and stores it in a list of dictionaries."""

    sites = [site for site_list in date_site_dict.values() for site in site_list]
    sites_set = set()
    unique_sites = []
    for site in sites:
        if site not in sites_set:
            sites_set.add(site)
            unique_sites.append(site)

    outer_site_dict = {site: None for site in sites_set}

    REPEAT_SITE = False

    if len(sites) != len(sites_set):
        print("There appears to be at least one site that spans across multiple days.\n"
        "We assume that site information is consistent over time.\n"
        "Please give the site multiple unique names if you would like to have differing information for the "
        "same location over multiple days.\n")

        REPEAT_SITE = True

    if not empty:
        categories = get_list_input(f"Please enter a comma-separated {GREEN}list of categories{RESET} of additional site information "
        "you would like to include \n(e.g., description, observation-category).\n"
        "The categories of site-name and city will already be provided, so no need to enter those: ")
        print()
        
        print("If you have nothing to enter for a given category (other than city), "
        "feel free to press enter and move on to the next category.\n")
    else:
        categories = []

    categories.insert(0, "city")

    if not REPEAT_SITE:
        same_info_same_date = input("Will site attributes be the same for all sites visited on the same date?\n"
        "If you enter 'yes', you will enter site information by date. If you enter 'no', you will enter site information by site (yes/no): ").strip().lower()
        print()

    if (not REPEAT_SITE) and (same_info_same_date in ["yes", "y"]):
        for date in date_list:
            print(f"{GREEN}{date}{RESET}\n")

            site_dict = {}

            for category in categories:
                while True:
                    info_input = input(f"{category}: ").strip()
                    
                    if info_input == "exit":
                        exit()
                    if info_input:
                        break
                    if category == "city":
                        print("City is required. Please enter a value. Enter 'exit' to quit.\n")
                    else:
                        break

                site_dict[category] = info_input
            
            print()

            date_sites = date_site_dict[date]

            for site in date_sites:
                unique_site_dict = site_dict.copy()
                unique_site_dict["site-name"] = site

                outer_site_dict[site] = unique_site_dict
    else:
        for site in unique_sites:
            print(f"{GREEN}{site}{RESET}\n")

            site_dict = {}

            site_dict["site-name"] = site

            for category in categories:
                while True:
                    info_input = input(f"{category}: ").strip()
                    
                    if info_input == "exit":
                        exit()
                    if info_input:
                        break
                    if category == "city":
                        print("City is required. Please enter a value. Enter 'exit' to quit.\n")
                    else:
                        break

                site_dict[category] = info_input

            print()

            outer_site_dict[site] = site_dict

    return outer_site_dict


def main():
    print("\nThis program helps organize your data collection directory to work smoothly with ipro-locator. \n\n"
      f"Please be prepared with the {GREEN}dates{RESET} you will be collecting data, "
      f"the {GREEN}sites{RESET} to be visited on those dates, "
      f"and the {GREEN}people{RESET} that will be taking photos. "
      f"Optionally, be prepared with {GREEN}site attributes{RESET} as well.\n"
      "You may enter 'exit' at any time if you would like to quit.\n")

    proceed = input("Would you like to proceed? (yes/no): ").strip().lower()
    print()

    # if they choose to proceed
    if proceed in ["yes", "y"]:
        # get dates to create date folders
        date_list = get_date_input()
        # get sites to create site folders
        date_site_dict = get_sites(date_list)

        # option to provide information corresponding to the sites
        additional_info = input(f"For each site, we will ask for the {GREEN}city/town{RESET} it is in (or nearest to). "
        f"Would you like to enter {GREEN}additional{RESET} site information "
        "(description, observation-category, etc)? (yes/no): ").strip().lower()
        print()

        # create dictionaries for each site
        if additional_info in ["yes", "y"]:
            site_information_dict = get_site_information(date_site_dict, date_list)
        else:
            site_information_dict = get_site_information(date_site_dict, date_list, empty=True)

        # get list of photographers
        photographers = get_list_input(f"Please enter a comma-separated list of the {GREEN}names{RESET} of people that will be taking photographs:")
        print()

        # naming the outermost directory
        while True:
            directory = input(
                f"What would you like to name the {GREEN}overarching directory{RESET}?\n"
                "The directory can be an existing directory if it was previously created using this script. \n"
                "If you would like it to be created in a location other than your current directory, "
                "please indicate that (../../image_folder): "
            ).strip()

            if directory:
                break
            else:
                print("\nPlease enter a directory name.\n")

        print()

        # creating all of the directories
        overarch_path = Path(directory)
        overarch_path.mkdir(parents=True, exist_ok=True)

        # loops through dates, sites, photographers, creates site.yaml files
        for date, site_list in date_site_dict.items():
            date_path = overarch_path / date
            date_path.mkdir(parents=True, exist_ok=True)

            for site in site_list:
                site_path = date_path / site
                site_path.mkdir(parents=True, exist_ok=True)

                site_dict = site_information_dict.get(site)
                if site_dict:
                    with open(overarch_path / f"{site}.yaml", "w") as file:  
                        yaml.dump(site_dict, file) 

                for photographer in photographers:
                    photographer_path = site_path / photographer
                    photographer_path.mkdir(parents=True, exist_ok=True)

        # prints structure
        print("Below is the created (or updated) directory structure:\n")
        print_directory_structure(directory)
        print()
        print("Please upload images by photographer in the corresponding photographer folders.\n"
        "Make sure that your photo-taking devices are location-enabled.\n"
        "Feel free to update and add to site information in the site.yaml files.\n"
        "If you would like to add new categories of site information, "
        "please follow the formatting of the rows already present.\n\n"
        f"It you want to run this script again to create more folders in {directory}, you may.\n"
        "For example, if you don't know the sites you will be visiting until the day before data collection, \n"
        "you can re-run this script when you have sites planned and add to the existing directory. \n\n"
        "Thank you!\n")

    else:
        exit()

if __name__ == "__main__":
    main()