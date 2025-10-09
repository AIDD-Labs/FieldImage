# Copyright (c) 2025 Eli Knodel
# Licensed under the BSD 3-Clause License. See LICENSE file for details.

# If I decide to and can delete images based on PII, give them these original filenames too

import argparse
import pandas as pd
import yaml
import exifread
import numpy as np
import subprocess
import re
import torch
import torchvision.models as models
import torchvision.transforms as transforms
import os
import matplotlib.pyplot as plt
import math
import sys
import folium

from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from torchvision.models import ResNet50_Weights
from sklearn.metrics.pairwise import cosine_similarity
from collections import defaultdict
from PIL import Image as PILImage

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

if project_root not in sys.path:
    sys.path.append(project_root)

from utils.constants import INPUT_IMAGE_EXTENSIONS, OUTPUT_IMAGE_EXTENSIONS
from utils.imageHelpers import convert_and_preserve_image_metadata, coord_to_decimal, frac_to_decimal, get_feature_vector, calc_max_pic_size, reduce_image
from utils.generalHelpers import is_valid_date_format


def valid_similarity_threshold(value):
    try:
        value = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid value: {value}. Please enter a number.")
    
    if not (0 <= value <= 1):  # Enforcing range between 0 and 1
        raise argparse.ArgumentTypeError(f"Threshold must be between 0 and 1. You entered: {value}")
    
    return value


def create_initial_spreadsheet(input, sites_bool):
    """The result of this function is a not-yet organized spreadsheet with information regarding the inputted directory structure.
       If sites_bool is true, the sites.yaml is referenced to provide site information associated with images and a site table is created."""

    print("Creating initial spreadsheet...")

    if sites_bool:
        site_desc_extension = "yaml"

        outer_site_dict = {}

        for file in input.iterdir():
            if file.name.lower().endswith(site_desc_extension):
                site_name = file.stem

                file_path = input / file

                with open(file_path, "r") as yaml_file:
                    site_dict = yaml.safe_load(yaml_file)
                    site_categories_lowered = {key.lower() for key in site_dict.keys()}
                    site_dict_lowered = {key.lower(): value for key, value in site_dict.items()}

                    if "city" not in site_categories_lowered:
                        print(f"❌ City was not provided in {file_path}.\n"
                              "Please ensure that each site.yaml file has city information. Exiting now...")
                        exit()

                    city_value = site_dict_lowered["city"]

                    if not city_value:
                        print(f"❌ There was no value for city in {file_path}.\n"
                              "Please ensure that each site.yaml file has city information. Exiting now...")
                        exit()

                    outer_site_dict[site_name] = site_dict

        site_descriptors = set()

        for site, site_dict in outer_site_dict.items():
            for descriptor in site_dict.keys():
                site_descriptors.add(descriptor.strip())

        sites = outer_site_dict.keys()

        data = {descriptor: [] for descriptor in site_descriptors}
        data["date"] = []
        data["photographer"] = []
        data["input-image-name"] = []
        data["input-image-folder"] = []

    else:
        data = {
            'input-image-name': [],
            'input-image-folder': [],
        }

    for folder in input.glob("**/"):
        for file in folder.iterdir():
            # if the file is an image
            if any(file.name.lower().endswith(extension) for extension in INPUT_IMAGE_EXTENSIONS):
                modified_folder = folder.relative_to(input)

                data['input-image-name'].append(file.name)
                data['input-image-folder'].append(modified_folder)

            if sites_bool:
                site_dir = folder.parent
                date_dir = site_dir.parent

                for site in sites:
                    if site_dir.name == site:
                        # list of site descriptors to make sure all sites have the same descriptors, even if the yamls differ in their attributes
                        site_descriptors_check = site_descriptors.copy()
                        site_dict = outer_site_dict[site]

                        date = date_dir.name
                        date_obj = datetime.strptime(date, "%Y-%m-%d")
                        photographer = folder.name

                        data["date"].append(date_obj)
                        data["photographer"].append(photographer)

                        for descriptor, value in site_dict.items():
                            data[descriptor].append(value)
                            site_descriptors_check.remove(descriptor)

                        # adding in empty values for additional descriptors
                        for descriptor in site_descriptors_check:
                            data[descriptor].append('')

    df = pd.DataFrame(data)

    if sites_bool:
        sites_df = df.drop(columns=["date", "photographer", "input-image-name", "input-image-folder"])
        sites_df = sites_df.drop_duplicates()
    else:
        sites_df = None

    print("✅\n")
    return df, sites_df


def create_output_directory_and_spreadsheet(input, output, df, sites_df, sites_bool):
    """This creates the output directory. For unorganized data, the output directory has the exact same structure 
       as the input directory. For organized data, the output directory is structured by cities the images were taken.
       In both cases, there is an optional check to make sure that the size and number of files are identical between the two directories.
       This uses exif data to get time and location of images and adds many rows to the dataframe describing the images, their names,
       and their location in the output directory."""

    if output.exists():
        print(f"Error: Output directory '{output}' already exists!\n")
        exit()

    print("Extracting time and location data...")

    df["date-time"] = None
    df["latitude"] = None
    df["longitude"] = None
    df["altitude-m"] = None
    df["direction-deg"] = None
    df["latitude-reference"] = None
    df["longitude-reference"] = None
    df["altitude-m-reference"] = None
    df["direction-deg-reference"] = None
    df["output-image-folder"] = None
    df["output-image-name"] = None
    df["output-image-link"] = None
    df["TEMP-image-to-copy"] = None

    num_images = df.shape[0]
    temp_folder = "temp"

    for i, image in df.iterrows():
        print(f"Extracting metadata from image {i+1}/{num_images}", end="\r", flush=True)

        input_folder = image["input-image-folder"]
        input_name = image["input-image-name"]

        input_file_path = input / input_folder / input_name
        image_file_path = None
        image_to_copy = None

        pre_extension = Path(input_name).stem
        file_extension = Path(input_name).suffix

        try:
            file_info = subprocess.run(["file", input_file_path], capture_output=True, text=True, check=True)
            file_info = file_info.stdout.strip()
            actual_file_type = file_info.split(":")[1].split(",")[0].strip()
        except (FileNotFoundError, subprocess.CalledProcessError, IndexError):
            # Fallback for Windows
            try:
                with PILImage.open(input_file_path) as img:
                    actual_file_type = f"{img.format} image data"
            except Exception as e:
                actual_file_type = "Unknown"

        METADATA_READY = False

        if actual_file_type.lower().startswith("jpeg"):
            image_file_path = input_file_path
            METADATA_READY = True

        NOT_JPEG_BUT_READY = (file_extension.lower() not in ['.jpg', '.jpeg']) and METADATA_READY

        if (not METADATA_READY) or NOT_JPEG_BUT_READY:
            jpeg_extension = ".JPEG"
            temp_name = pre_extension + jpeg_extension
            file_path = output / temp_folder / temp_name

            # the below and the while loop are to make sure we aren't overwriting image files
            # (same name and different extensions prior to being put in temp folder)
            image_base = output / temp_folder / pre_extension
            counter = 1

            while file_path.exists():
                new_name = f"{image_base}_{counter}{jpeg_extension}"
                file_path = Path(new_name) 
                counter += 1

            if not METADATA_READY:
                image_file_path = file_path
            else:
                image_to_copy = file_path
            try:
                if not METADATA_READY:
                    convert_and_preserve_image_metadata(input_file_path, image_file_path)
                    image_to_copy = image_file_path
                else:
                    convert_and_preserve_image_metadata(input_file_path, image_to_copy)
            except Exception as e:
                # get rid of the below print statement eventually
                print(f"An unexpected error occurred while converting this image to JPEG: {input_file_path}: {e}")
                continue
        else:
            image_to_copy = input_file_path

        df.at[i, "TEMP-image-to-copy"] = image_to_copy

        with open(image_file_path, "rb") as image_file:
            tags = exifread.process_file(image_file)

        try:
            time = tags.get("EXIF DateTimeOriginal").values
            time_obj = datetime.strptime(time, "%Y:%m:%d %H:%M:%S")
        except AttributeError:
            time_obj = None

        try:
            lat = tags.get("GPS GPSLatitude")
            decimal_lat = coord_to_decimal(lat)
        except AttributeError:
            decimal_lat = np.nan

        try:
            long = tags.get("GPS GPSLongitude")
            decimal_long = coord_to_decimal(long)
        except AttributeError:
            decimal_long = np.nan

        try:
            altitude = tags.get("GPS GPSAltitude")
            decimal_altitude = frac_to_decimal(altitude)
        except AttributeError:
            decimal_altitude = np.nan

        try:
            direction = tags.get("GPS GPSImgDirection")
            decimal_direction = frac_to_decimal(direction)
        except AttributeError:
            decimal_direction = np.nan

        try:
            lat_ref = tags.get("GPS GPSLatitudeRef").values
        except AttributeError:
            lat_ref = None

        try:
            long_ref = tags.get("GPS GPSLongitudeRef").values
        except AttributeError:
            long_ref = None

        try:
            altitude_ref = tags.get("GPS GPSAltitudeRef").values[0]
        except IndexError:
            try:
                altitude_ref = tags.get("GPS GPSAltitudeRef").values
            except:
              altitude_ref = np.nan
        except AttributeError:
            altitude_ref = np.nan

        try:
            direction_ref = tags.get("GPS GPSImgDirectionRef").values
        except AttributeError:
            direction_ref = None

        df.at[i, "date-time"] = time_obj
        df.at[i, "latitude"] = decimal_lat
        df.at[i, "longitude"] = decimal_long
        df.at[i, "altitude-m"] = decimal_altitude
        df.at[i, "direction-deg"] = decimal_direction
        
        df.at[i, "latitude-reference"] = lat_ref
        df.at[i, "longitude-reference"] = long_ref
        df.at[i, "altitude-m-reference"] = altitude_ref
        df.at[i, "direction-deg-reference"] = direction_ref

    print("\n✅\n")

    print("Creating output directory with renamed images...")

    df["date-time"] = pd.to_datetime(df["date-time"])

    if sites_bool:
        df["date"] = pd.to_datetime(df["date"])

        df["date-time"] = df["date-time"].fillna(df["date"])
        df.drop('date', axis=1, inplace=True)

    df["date"] = df["date-time"].apply(lambda x: x.strftime("%Y-%m-%d") if pd.notna(x) else None)
    df["time"] = df["date-time"].apply(lambda x: x.strftime("%H:%M:%S") if pd.notna(x) else None)

    df.sort_values(by="date-time", ascending=True, inplace=True)

    if sites_bool:
        # determining site ids
        order_of_sites = pd.unique(df["site-name"])
        num_sites = len(order_of_sites)
        num_sites_len = len(str(num_sites))

        site_id_dict = {}

        for index, site in enumerate(order_of_sites):
            site_number = index + 1
            index_len = len(str(site_number))
            site_id = "S"
            for i in range(num_sites_len - index_len):
                site_id += "0"
            site_id += str(site_number)
            
            site_id_dict[site] = site_id

        df["site-id"] = None

        for i, image in df.iterrows():
            site_name = image["site-name"]
            site_id = site_id_dict[site_name]
            df.at[i, "site-id"] = site_id

        sites_df["site-id"] = None

        for j, site in sites_df.iterrows():
            site_name = site["site-name"]
            site_id = site_id_dict[site_name]
            sites_df.at[j, "site-id"] = site_id

    num_images_len = len(str(num_images))

    df.reset_index(drop=True, inplace=True)
    df['photo-id'] = "P" + (df.index + 1).astype(str).str.zfill(num_images_len)

    # loop to copy and rename images, as well as fill in output columns
    for i, image in df.iterrows():
        print(f"Copying image {i+1}/{num_images}", end="\r", flush=True)

        image_to_copy = image["TEMP-image-to-copy"]
        date_time = image["date-time"]
        date_for_name = ""

        # haven't been able to test this yet
        if pd.isna(date_time):
            date_for_name = "NODATE"
        else:
            date_for_name = date_time.strftime("%Y%m%d")

        photo_id = image["photo-id"]

        extension = image_to_copy.suffix

        if sites_bool:
            site_id = image["site-id"]

            # the below variable and for loop are to get the city variable in case the casing is not what is anticipated
            city_col_name = ""

            col_names = df.columns.tolist()

            for col_name in col_names:
                if col_name.lower() == "city":
                    city_col_name = col_name
                    break

            city = image[city_col_name]

            site_name = image["site-name"]
            first_word_site = site_name.split()[0]

            photographer = image["photographer"]
            names = re.split(r'[ -]', photographer)
            name_count = len([name for name in names if name]) # the if name is to avoid empty strings

            if name_count >= 2:
                photographer_name = [name[0].upper() for name in names if name] # this generates initials
            else:
                photographer_name = photographer

            output_folder = city
            output_name = date_for_name + "_" + site_id + "-" + photo_id + "_" + city + "_" + first_word_site + "_" + photographer_name + extension
        else:
            input_folder = image["input-image-folder"]

            output_folder = input_folder
            output_name = date_for_name + "_" + photo_id + extension
            
        output_file_path = output / output_folder / output_name

        convert_and_preserve_image_metadata(image_to_copy, output_file_path)

        df.at[i, "output-image-folder"] = output_folder
        df.at[i, "output-image-name"] = output_name

    df['output-image-link'] = df.apply(
        lambda row: f'=HYPERLINK("{Path("..") / Path(row["output-image-folder"]) / row["output-image-name"]}", "{row["output-image-name"]}")', 
        axis=1
    )

    temp_dir = output / temp_folder

    if temp_dir.exists() and temp_dir.is_dir():
        for item in temp_dir.iterdir():
            item.unlink()
        
        temp_dir.rmdir()

    df.drop('TEMP-image-to-copy', axis=1, inplace=True)

    df.insert(0, "photo-id", df.pop("photo-id"))

    datetime_col = df.columns.get_loc("date-time")
    df.insert(datetime_col + 1, "date", df.pop("date"))
    df.insert(datetime_col + 2, "time", df.pop("time"))

    direction_ref_col = df.columns.get_loc("direction-deg-reference")
    df.insert(direction_ref_col, "input-image-folder", df.pop("input-image-folder"))

    input_folder_col = df.columns.get_loc("input-image-folder")
    df.insert(input_folder_col, "input-image-name", df.pop("input-image-name"))
    
    if sites_bool:
        df.insert(1, "site-id", df.pop("site-id"))
        df.insert(2, "site-name", df.pop("site-name"))

        sites_df.insert(0, "site-id", sites_df.pop("site-id"))
        sites_df.insert(1, "site-name", sites_df.pop("site-name"))

    print("\n✅\n")

    return df, sites_df


def check_directory_structure(input):
    """Verify the directory structure of the input directory works for getting site information. ChatGPT"""
    VALID = True

    # check that there are directories:
    no_directories = not any(path.is_dir() for path in input.iterdir())
    
    if no_directories:
        VALID = False

    # actual site.yaml files
    site_yaml_files = {f.name for f in input.glob("*.yaml")}
    
    for date_path in input.iterdir():
        if not date_path.is_dir():
            continue

        if not is_valid_date_format(date_path.name):
            print(f"❌ Error: '{date_path.name}' does not follow the YYYY-MM-DD format.")
            VALID = False
            continue
        
        for site_path in date_path.iterdir():
            if not site_path.is_dir():
                continue

            # the below is what the site.yaml file should be called
            site_yaml = f"{site_path.name}.yaml"
            if site_yaml not in site_yaml_files:
                print(f"❌ Error: Missing YAML file for site '{site_path.name}'")
                VALID = False

            # ensure there is at least one photographer subdirectory
            photographer_dirs = [p for p in site_path.iterdir() if p.is_dir()]
            if not photographer_dirs:
                print(f"❌ Error: No photographer subdirectories in '{site_path.name}'")
                VALID = False

            # ensure there are no directories below the photographer level
            for photographer in photographer_dirs:
                sub_dirs = [p for p in photographer.iterdir() if p.is_dir()]
                if sub_dirs:
                    modified_photographer = photographer.relative_to(input)
                    print(f"❌ Error: Photographer directory '{modified_photographer}' should not contain subdirectories.")
                    VALID = False
    
    return VALID


def delete_similar_images(input, output, df, sites_bool, delete_threshold):
    """Identifies and deletes duplicate images using deep learning"""
    
    print("Preparing to identify and delete similar images...")

    # using an existing torch model - ChatGPT
    model = models.resnet50(weights=ResNet50_Weights.DEFAULT)
    model = torch.nn.Sequential(*list(model.children())[:-1]) 
    model.eval()

    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])

    image_paths = []

    # getting all image paths
    for file in output.rglob("*"):
        if file.is_dir():
            continue
            
        if any(file.name.lower().endswith(extension) for extension in OUTPUT_IMAGE_EXTENSIONS):
            image_paths.append(file)

    num_images = len(image_paths)

    feature_vectors = {}

    # getting feature vectors for images
    for i, path in enumerate(image_paths):
        print(f"Getting feature vector for image {i+1}/{num_images}", end="\r", flush=True)

        vector = get_feature_vector(path, model, transform)
        feature_vectors[path] = vector

    print()

    # this keeps track of images in df to update after deletion
    index_of_images_in_df = {}

    # creating data dictionary to be turned into df
    data = {}

    # the ones that say input refer to input images, otherwise, they refer to output images
    data["input-image-1-folder"] = [] 
    data["input-image-1-name"] = []
    data["input-image-2-folder"] = []
    data["input-image-2-name"] = []
    data["image-1-folder"] = [] 
    data["image-1-name"] = []
    data["image-1"] = []
    data["image-2-folder"] = []
    data["image-2-name"] = []
    data["image-2"] = []
    data["similarity"] = []

    if sites_bool:
        data["same-site"] = []

    # adding column to image table to indicate if each image had image(s) similar to it that were deleted
    df['similar-image-deleted'] = False

    # putting the above column between location and file data
    direction_ref_loc = df.columns.get_loc("direction-deg-reference")
    df.insert(direction_ref_loc + 1, "similar-image-deleted", df.pop("similar-image-deleted"))
    
    # comparing image feature vectors
    for i in range(len(image_paths)):
        for j in range(i + 1, len(image_paths)):
            print(f"Comparing images {i+1} and {j+1}", end="\r", flush=True)

            first_image = image_paths[i]
            second_image = image_paths[j]

            vec1 = feature_vectors[first_image]
            vec2 = feature_vectors[second_image]

            if vec1 is not None and vec2 is not None:
                similarity = cosine_similarity([vec1], [vec2])[0][0]

                # if they are sufficiently similar, add image information as a row in df
                if similarity >= delete_threshold:
                    first_parent = first_image.parent
                    first_folder = first_parent.relative_to(output)
                    first_image_name = first_image.name

                    second_parent = second_image.parent
                    second_folder = second_parent.relative_to(output)
                    second_image_name = second_image.name

                    data["image-1-folder"].append(first_folder)
                    data["image-1-name"].append(first_image_name)
                    data["image-1"].append(first_image)
                    data["image-2-folder"].append(second_folder)
                    data["image-2-name"].append(second_image_name)
                    data["image-2"].append(second_image)
                    data["similarity"].append(similarity)

                    first_image_index = df.index[df['output-image-name'] == first_image_name][0]
                    second_image_index = df.index[df['output-image-name'] == second_image_name][0]

                    if first_image not in index_of_images_in_df:
                        index_of_images_in_df[first_image] = first_image_index
                    if second_image not in index_of_images_in_df:
                        index_of_images_in_df[second_image] = second_image_index

                    # adding input image information to df
                    data["input-image-1-folder"].append(df.at[first_image_index, "input-image-folder"])
                    data["input-image-1-name"].append(df.at[first_image_index, "input-image-name"])
                    data["input-image-2-folder"].append(df.at[second_image_index, "input-image-folder"])
                    data["input-image-2-name"].append(df.at[second_image_index, "input-image-name"])

                    if sites_bool:
                        first_site = first_image_name.split("_")[1].split("-")[0]
                        second_site = second_image_name.split("_")[1].split("-")[0]

                        if first_site == second_site:
                            data["same-site"].append(True)
                        else:
                            data["same-site"].append(False)

    similarity_df = pd.DataFrame(data)
    num_pairs = len(similarity_df)

    print()
    print(f"\nFound {num_pairs} pairs of similar images.")

    # creating hyperlinks for input and output image pairs
    similarity_df['input-image-1-link'] = similarity_df.apply(
        lambda row: f'=HYPERLINK("{Path(os.path.relpath(input / Path(row["input-image-1-folder"]) / row["input-image-1-name"], start=output / "_SIMILAR_IMAGES"))}", "{row["input-image-1-name"]}")', 
        axis=1
    )

    similarity_df['input-image-2-link'] = similarity_df.apply(
        lambda row: f'=HYPERLINK("{Path(os.path.relpath(input / Path(row["input-image-2-folder"]) / row["input-image-2-name"], start=output / "_SIMILAR_IMAGES"))}", "{row["input-image-2-name"]}")', 
        axis=1
    )

    similarity_df['image-1-link'] = similarity_df.apply(
        lambda row: f'=HYPERLINK("{Path("..") / Path(row["image-1-folder"]) / row["image-1-name"]}", "{row["image-1-name"]}")', 
        axis=1
    )

    similarity_df['image-2-link'] = similarity_df.apply(
        lambda row: f'=HYPERLINK("{Path("..") / Path(row["image-2-folder"]) / row["image-2-name"]}", "{row["image-2-name"]}")', 
        axis=1
    )

    # inserting columns with links at a specific location (end of each little grouping)
    input_image_1_loc = similarity_df.columns.get_loc("input-image-1-name")
    similarity_df.insert(input_image_1_loc + 1, "input-image-1-link", similarity_df.pop("input-image-1-link"))

    input_image_2_loc = similarity_df.columns.get_loc("input-image-2-name")
    similarity_df.insert(input_image_2_loc + 1, "input-image-2-link", similarity_df.pop("input-image-2-link"))

    image_1_loc = similarity_df.columns.get_loc("image-1")
    similarity_df.insert(image_1_loc, "image-1-link", similarity_df.pop("image-1-link"))

    image_2_loc = similarity_df.columns.get_loc("image-2")
    similarity_df.insert(image_2_loc, "image-2-link", similarity_df.pop("image-2-link"))

    if sites_bool:
        diff_sites_df = similarity_df[similarity_df['same-site'] == False]
        similarity_df = similarity_df[similarity_df['same-site'] == True]

    image_default_dict = defaultdict(set)

    for image_1, image_2 in zip(similarity_df['image-1'], similarity_df['image-2']):
        image_default_dict[image_1].add(image_2)
        image_default_dict[image_2].add(image_1)
    
    # turning it into a normal dict
    image_dict = {key: list(value) for key, value in image_default_dict.items()}

    # sorting by length of value lists to delete images with multiple matches first
    image_dict = dict(sorted(image_dict.items(), key=lambda item: len(item[1]), reverse=True))
    image_dict_to_modify = image_dict.copy()

    image_delete_list = []

    # if image has 2 or more matches, delete it and update number of matches
    while any(len(similar_images) >= 2 for similar_images in image_dict_to_modify.values()):
        duplicate_image = next(iter(image_dict_to_modify))
        similar_images = image_dict_to_modify[duplicate_image]

        image_delete_list.append(duplicate_image)
        image_dict_to_modify[duplicate_image] = []

        for image in similar_images:
            image_dict_to_modify[image].remove(duplicate_image)

        # sorting again in case we go through the loop again
        image_dict_to_modify = dict(sorted(image_dict_to_modify.items(), key=lambda item: len(item[1]), reverse=True))

    
    image_deleted = []

    # at this point, we should only have one similar image per unique image
    # loop through similarity df and add image_2's as the image to delete
    # if one has not yet been deleted in the pair
    for i, image in similarity_df.iterrows():
        image_1 = image["image-1"]
        image_2 = image["image-2"]

        if (image_1 in image_delete_list) and (image_2 in image_delete_list):
            image_deleted.append("both")
        elif (image_1 in image_delete_list):
            image_deleted.append("image-1")
            # determining kept image
            second_image_index = df.index[df['output-image-name'] == image["image-2-name"]][0]
            df.loc[second_image_index, 'similar-image-deleted'] = True
        elif (image_2 in image_delete_list):
            image_deleted.append("image-2")
            # determining kept image
            first_image_index = df.index[df['output-image-name'] == image["image-1-name"]][0]
            df.loc[first_image_index, 'similar-image-deleted'] = True
        else:
            image_delete_list.append(image_2)
            image_deleted.append("image-2")
            # determining kept image
            first_image_index = df.index[df['output-image-name'] == image["image-1-name"]][0]
            df.loc[first_image_index, 'similar-image-deleted'] = True

    similarity_df["output-image-deleted"] = image_deleted

    num_images_to_delete = len(image_delete_list)

    print(f"Deleting {num_images_to_delete} images...")

    # actually deleting images and dropping rows corresponding to those images 
    for image in image_delete_list:
        if image.exists():
            image.unlink()

        df_index = index_of_images_in_df[image]
        df.drop(index=df_index, inplace=True)

    print("✅\n")

    similarity_df.drop(
        columns=["image-1-folder", "image-1-name", "image-1-link", "image-1", 
                 "image-2-folder", "image-2-name", "image-2-link", "image-2"], 
        inplace=True
    )

    if sites_bool:
        similarity_df.drop(
            columns=["same-site"],
            inplace=True
        )

    sim_spreadsheet_name = output / "_SIMILAR_IMAGES" / "similarity_delete_table.xlsx"
    sim_spreadsheet_name.parent.mkdir(parents=True, exist_ok=True)

    similarity_df.to_excel(sim_spreadsheet_name, index=False)

    if sites_bool:
        if len(diff_sites_df) > 0:
            already_deleted_one_or_both = []

            single_data = {}

            single_data["image-folder"] = []
            single_data["image-name"] = []
            single_data["image-link"] = []

            for i, image in diff_sites_df.iterrows():
                image_1 = image["image-1"]
                image_2 = image["image-2"]

                if (image_1 in image_delete_list) and (image_2 in image_delete_list):
                    already_deleted_one_or_both.append(i)
                elif image_1 in image_delete_list:
                    already_deleted_one_or_both.append(i)
                    
                    single_data["image-folder"].append(image["image-2-folder"])
                    single_data["image-name"].append(image["image-2-name"])
                    single_data["image-link"].append(image["image-2-link"])
                elif image_2 in image_delete_list:
                    already_deleted_one_or_both.append(i)
                    
                    single_data["image-folder"].append(image["image-1-folder"])
                    single_data["image-name"].append(image["image-1-name"])
                    single_data["image-link"].append(image["image-1-link"])

            # this is for if we delete one of a pair of images in which the pair were of different sites
            # these images' sites may need reclassified
            if len(single_data['image-name']) > 0:
                verify_city_df = pd.DataFrame(single_data)
                spreadsheet_name = output / "_SIMILAR_IMAGES" / "verify_site_ids.xlsx"
                verify_city_df.to_excel(spreadsheet_name, index=False)

            if len(already_deleted_one_or_both) > 0:
                diff_sites_df = diff_sites_df.drop(already_deleted_one_or_both)

            if len(diff_sites_df) > 0:
                diff_sites_df.drop(
                    columns=["input-image-1-link", "input-image-2-link", "image-1", "image-2", "same-site"], 
                    inplace=True
                )

                spreadsheet_name = output / "_SIMILAR_IMAGES" / "similar_images_different_sites.xlsx"
                diff_sites_df.to_excel(spreadsheet_name, index=False)

    return df


def compress_images(output, max_size_gb):
    """Optimally reduces the size of large images to fit a total data size threshold"""

    print("Getting image sizes and preparing to compress...")

    image_paths = []

    for file in output.rglob("*"):
        if file.is_dir():
            continue
            
        if any(file.name.lower().endswith(extension) for extension in OUTPUT_IMAGE_EXTENSIONS):
            image_paths.append(Path(file))

    image_sizes = []

    for image in image_paths:
        size_bytes = image.stat().st_size
        size_mb = size_bytes / (1024**2)
        image_sizes.append(size_mb)

    size_df = pd.DataFrame({'image-file-path': image_paths, 'image-size': image_sizes})
    size_df = size_df.sort_values(by='image-size', ascending=True)
    size_df.reset_index(inplace=True, drop=True)

    # saving a figure of the image distribution for reference
    plt.hist(size_df['image-size'], bins=30)

    plt.xlabel("Image Size (MB)")
    plt.ylabel("Frequency")

    pre_compress_fig_name = output / "_IMAGE_SIZE_DISTRIBUTIONS" / "PRE_compress_image_size_dist.svg"
    pre_compress_fig_name.parent.mkdir(parents=True, exist_ok=True)

    plt.savefig(pre_compress_fig_name)
    plt.clf()

    MAX_TOT_SIZE_MB = max_size_gb * 1024
    num_images = len(size_df)

    FIRST_IMAGE_NEEDING_COMPRESSED = True

    data_to_work_with = MAX_TOT_SIZE_MB
    images_to_go = num_images
    images_to_compress = 0
    index = 1
    # initially, the max size of an image assumes that all images have equal size
    max_pic_size_mb = calc_max_pic_size(images_to_go, MAX_TOT_SIZE_MB)

    # the max size increases as we iterate through a dataframe that is sorted in ascending order
    # images that are smaller than the average size will not need compressed and free up more space for larger images
    for i, image in size_df.iterrows():
        image_size = size_df.at[i, "image-size"]
    
        if image_size <= max_pic_size_mb:
            data_to_work_with -= image_size
            images_to_go -= 1
            # max size increases while images are smaller than the average size needed
            max_pic_size_mb = calc_max_pic_size(images_to_go, data_to_work_with)
        else:
            # here we will want to compress images

            # once we hit our first image larger than the max size, the size to reduce to is set
            # all future images will need to be reduced to size_reduction
            if FIRST_IMAGE_NEEDING_COMPRESSED:
                size_reduction = math.floor(max_pic_size_mb * 100) / 100
                FIRST_IMAGE_NEEDING_COMPRESSED = False

                images_to_compress = images_to_go
                print(f"Images larger than {size_reduction} MB will be compressed.")

            print(f"Compressing image {index}/{images_to_compress}", end="\r", flush=True)

            new_size = reduce_image(size_df.at[i, "image-file-path"], size_reduction, step=5)
            size_df.at[i, "image-size"] = new_size

            index += 1

    print("\n✅\n")
    
    plt.hist(size_df['image-size'], bins=30)

    plt.xlabel("Image Size (MB)")
    plt.ylabel("Frequency")

    # saving a figure of the image distribution for reference
    post_compress_fig_name = output / "_IMAGE_SIZE_DISTRIBUTIONS" / "POST_compress_image_size_dist.svg"

    plt.savefig(post_compress_fig_name)
    plt.clf()

    # issue with image orientation being lost in reduced images


def create_map(output, df, sites_bool):
    """Creates a simple map to quickly view the image locations"""

    print("Creating image map...")

    # only mapping images with a location
    df_no_nan = df.dropna(subset=["latitude", "longitude"])
    # excluding the folder columns and the hyperlink since they can cause problems if they have "\"
    excluded_columns = {"input-image-folder", "output-image-folder", "output-image-link"}

    image_map = folium.Map(location=[0, 0], zoom_start=2)

    # to check if there is already an image on the map at a location where another image is being displayed
    existing_locations = set()
    # amount to offset in x or y if there are images at the same location
    OFFSET = 0.00005

    # function to find a unique location to display the image
    # this result in a diagonal stack of images (bottom left being the first one and the actual location)
    def get_unique_location(lat, lon, existing_locations):
        while (lat, lon) in existing_locations:
            lat += OFFSET
            lon += OFFSET
        return lat, lon

    if sites_bool:
        sites = df_no_nan['site-id'].unique()

        available_colors = [
            'red', 'blue', 'green', 'purple', 'orange', 'darkred', 'lightred',
            'beige', 'darkblue', 'darkgreen', 'cadetblue', 'darkpurple', 'white',
            'pink', 'lightblue', 'lightgreen', 'gray', 'black', 'lightgray'
        ]

        color_map = {
            value: available_colors[i % len(available_colors)]
            for i, value in enumerate(sites)
        }

    # iterates through df, adding a marker and a popup for each image
    for i, image in df_no_nan.iterrows():

        image_path = (Path(image["output-image-folder"]) / image["output-image-name"])
        image_path = image_path.as_posix()

        html = f"""
            <h4>{image['output-image-name']}</h4>
            <img src="{image_path}" style="width: 100%; height: auto; max-width: 100%;">

            <div style="max-height: 120px; overflow-y: auto; font-size: 10px; margin-top: 5px;">
            <table>
                {''.join(
                    f'<tr><td><b>{col}</b></td><td>{image[col]}</td></tr>'
                    for col in image.index if col not in excluded_columns
                )}
            </table>
            </div>
        """

        popup = folium.Popup(html, max_width='auto')

        if sites_bool:
            site = image['site-id']
            marker_color = color_map.get(site, 'red')
        else:
            marker_color = 'red'

        lat = image['latitude']
        lon = image['longitude']
        lat_ref = image['latitude-reference']
        lon_ref = image['longitude-reference']

        if (lat_ref == "S"):
            lat *= -1
        if (lon_ref == "W"):
            lon *= -1

        unique_lat, unique_lon = get_unique_location(lat, lon, existing_locations)
        existing_locations.add((unique_lat, unique_lon))

        folium.Marker(
            location=[unique_lat, unique_lon],
            popup=popup,
            tooltip=image['output-image-name'],
            icon=folium.Icon(color=marker_color, icon='camera', prefix='fa')
        ).add_to(image_map)

    print("✅\n")

    image_map.save(output / "image_map.html")


def process_images(input, output, sites_bool, delete_threshold, max_size_gb):
    """This function will call all other functions, based on inputted arguments"""

    if not Path(input).is_dir():
        print(f"Error: {input} is not a valid directory.\n")
        exit()

    input_path = Path(input).resolve()
    output_path = Path(output).resolve()

    # check if the directory structure is appropriate for use with the sites flag
    if sites_bool:
        if not check_directory_structure(input_path): 
            print("\n❌ Directory does not follow the appropriate structure for use of the sites flag.\n"
            "Please fix the error above and try again. Exiting now...")
            exit()
        else:
            print("✅ Directory follows appropriate structure to include site and photographer information.\n")

    df, sites_df = create_initial_spreadsheet(input_path, sites_bool)
    df, sites_df = create_output_directory_and_spreadsheet(input_path, output_path, df, sites_df, sites_bool)
    if delete_threshold:
        df = delete_similar_images(input_path, output_path, df, sites_bool, delete_threshold)
    if max_size_gb:
        compress_images(output_path, max_size_gb)
    create_map(output_path, df, sites_bool)

    excel_spreadsheet = output_path / "_IMAGE_METADATA" / "image_metadata.xlsx"
    csv_spreadsheet = output_path / "_IMAGE_METADATA" / "image_metadata.csv"
    site_spreadsheet = output_path / "_IMAGE_METADATA" / "site_data.xlsx"
    excel_spreadsheet.parent.mkdir(parents=True, exist_ok=True)

    df.to_excel(excel_spreadsheet, index=False)
    df.to_csv(csv_spreadsheet, index=False)
    if sites_bool:
        sites_df.to_excel(site_spreadsheet, index=False)

    output_size_in_bytes = sum(f.stat().st_size for f in output_path.rglob("*") if f.is_file())
    output_size_in_gb = output_size_in_bytes / (1024**3)

    print(f"✅ Created directory {output} of size: {output_size_in_gb:.2f} GB")
    print(f"✅ Created spreadsheet: {excel_spreadsheet} \n")


def main():
    parser = argparse.ArgumentParser(description="This tool takes an input image directory and extracts image time and location data, " \
    "gives output images intuitive names based on their metadata, and creates an image data table that organizes and stores this metadata. " \
    "In addition, it creates an interactive map in which images and their locations and metadata can be viewed. " \
    "Output images are all converted to the JPEG file format. If your input image directory follows the hierarchy created by create-directory-sites, " \
    "use the -s flag to create an output image directory that files images by city and incorporates site information included in the site.yaml files into the image data table. " \
    "Using the -s flag, site and photographer information will also be included in the output image filenames. If your input image directory follows a different hierarchy, " \
    "the output image directory will be created under the same hierarchy as the input. Regardless of the structure of your input image directory, "
    "if you would like to delete similar images, or if you have a maximum data threshold that needs to be met, please indicate that using their associated flags (-d and -m).")

    parser.add_argument("-i", "--input-directory", required=True, help="Path to the directory containing images")
    parser.add_argument("-o", "--output-directory", required=True, help="Path for the output directory to be created")
    parser.add_argument("-s", "--sites", action="store_true", help="If your directory was created using 'create-directory-sites', "
    "this enables the inclusion of site information in the spreadsheet and image names. Please make sure that the 'city' category "
    "is included in each of your site.yaml files.")
    parser.add_argument("-d", "--delete-similar", nargs="?", const=0.94, type=valid_similarity_threshold, help="Deletes one of a pair of images in the new directory "
    "if they are determined to be similar based on your inputted threshold value. "
    "If no threshold value is entered, the recommended threshold of 0.94 will be used. "
    "Valid threshold values are between 0 (not similar) and 1 (identical). "
    "Information related to how the similar images are handled will be located in a folder called '_SIMILAR_IMAGES'")
    parser.add_argument("-m", "--max-size", type=float, help="If the sum of the data for all of the images "
    "needs to be below some threshold, enter it here in GB. "
    "Images of large sizes in the new directory will be optimally reduced to be below that threshold.")
    
    args = parser.parse_args()
    print()

    process_images(args.input_directory, args.output_directory, args.sites, args.delete_similar, args.max_size)

if __name__ == "__main__":
    main()