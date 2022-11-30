#   Copyright (c) 2022 by Autodesk, Inc.
#   Permission to use, copy, modify, and distribute this software in object code form
#   for any purpose and without fee is hereby granted, provided that the above copyright
#   notice appears in all copies and that both that copyright notice and the limited
#   warranty and restricted rights notice below appear in all supporting documentation.
#   AUTODESK PROVIDES THIS PROGRAM "AS IS" AND WITH ALL FAULTS. AUTODESK SPECIFICALLY
#   DISCLAIMS ANY IMPLIED WARRANTY OF MERCHANTABILITY OR FITNESS FOR A PARTICULAR USE.
#   AUTODESK, INC. DOES NOT WARRANT THAT THE OPERATION OF THE PROGRAM WILL BE
#   UNINTERRUPTED OR ERROR FREE.
import base64
import json
import os
from typing import TypedDict
import adsk.core
import adsk.fusion

# Configuration Options
CACHE_RESULTS = True
BASE_FOLDER_NAME = 'FusionDataUtils'
JSON_OUTPUT_FOLDER_NAME = 'json_output'

# Global Variables
app = adsk.core.Application.get()
ui = app.userInterface
base_folder = os.path.join(os.path.expanduser('~'), BASE_FOLDER_NAME)
json_output_folder = os.path.join(base_folder, JSON_OUTPUT_FOLDER_NAME, '')
results = {}
collection_id = app.data.activeSpaceCollectionId

# Initial folder creation for file cache
if CACHE_RESULTS:
    if not os.path.exists(base_folder):
        os.makedirs(base_folder)
    if not os.path.exists(json_output_folder):
        os.makedirs(json_output_folder)


# Typed dict definitions, primarily for python type hinting
class ComponentInfo(TypedDict):
    Name: str
    f3dComponentId: str
    ComponentId: str
    ComponentVersionId: str


class DesignInfo(TypedDict):
    Name: str
    DesignFileId: str
    DesignFileVersionId: str
    FolderId: str
    ProjectId: str
    HubId: str
    Components: list[ComponentInfo]
    AllComponents: list[ComponentInfo]


def get_fusion_data_ids_for_component(component: adsk.fusion.Component) -> ComponentInfo:
    """
    Returns the relevant Fusion Data API information for the given Component.
    The results are returned as a typed dictionary as described in README.md file.
    """
    component_parent_design = component.parentDesign
    data_file = component_parent_design.parentDocument.dataFile
    version_id = data_file.versionId

    component_result = _get_component_info_from_results_global(version_id, component)
    if component_result is not None:
        return component_result

    # Try to compute IDs for active design
    _generate_design_info(component_parent_design)

    component_result = _get_component_info_from_results_global(version_id, component)
    if component_result is not None:
        return component_result

    raise RuntimeError(f"Could not get Fusion Data API IDs for this Component: {component.name}")


def get_fusion_data_ids_for_active_document() -> DesignInfo:
    """
    Returns the relevant Fusion Data API information for the currently active document.
    The results are returned as a typed dictionary as described in README.md file.
    """
    # Get Design from active Document
    doc = adsk.fusion.FusionDocument.cast(app.activeDocument)
    design = doc.design
    return get_fusion_data_ids_for_design(design)


def get_fusion_data_ids_for_design(design: adsk.fusion.Design) -> DesignInfo:
    """
    Returns the relevant Fusion Data API information for the given Design.
    The results are returned as a typed dictionary as described in README.md file.
    """
    design_data_file = design.parentDocument.dataFile
    design_version_id = design_data_file.versionId

    # If results already exist return them
    mem_cache_design_version = results.get(design_version_id, None)
    if mem_cache_design_version is not None:
        _refresh_design_info_result(design_version_id, mem_cache_design_version, design_data_file)
        return results[design_version_id]

    # Try to compute IDs for active design
    _generate_design_info(design)

    # If results now exist return them
    if results.get(design_version_id, False):
        return results[design_version_id]

    # Raise an error if IDs could not be computed
    raise RuntimeError(f"Could not get Fusion Data API IDs for: {design.parentDocument.name}")


# Get relevant PIM data for design
def _generate_design_info(design):
    global collection_id

    design_data_file = design.parentDocument.dataFile
    design_version_id = design_data_file.versionId

    if CACHE_RESULTS:
        disk_cache_design_version: DesignInfo = _read_versions_file(design_version_id)
        if disk_cache_design_version is not None:
            _refresh_design_info_result(design_version_id, disk_cache_design_version, design_data_file)
            return

    collection_id = app.data.activeSpaceCollectionId
    _ensure_file_version_in_results(design_data_file)
    structured_pim_data = _make_structured_pim_data(design)
    _generate_component_info_for_design(design_version_id, design, structured_pim_data)

    if CACHE_RESULTS:
        _write_results()


# Get relevant PIM data (Fusion Data API IDs) for Components in design
def _generate_component_info_for_design(design_version_id: str, design: adsk.fusion.Design, pim_data: dict):
    for component in design.allComponents:
        component_data_file = component.parentDesign.parentDocument.dataFile
        component_lineage_id = component_data_file.id
        component_version_id = component_data_file.versionId

        _ensure_file_version_in_results(component_data_file)
        pim_data_for_component_parent_file: dict = pim_data.get(component_lineage_id)

        if pim_data_for_component_parent_file:
            # Get Component and ComponentVersion IDs and commit result
            component_info = _make_component_info(component, pim_data_for_component_parent_file)
            results[component_version_id]['Components'].append(component_info)
            results[design_version_id]['AllComponents'].append(component_info)


# Create a map of component.id to Space/Assets
# Component.id is only guaranteed to be unique per file
# Store results grouped by parent files (in the case of a distributed design)
def _make_structured_pim_data(design: adsk.fusion.Design) -> dict:
    pim_data = {}

    # This is an undocumented API to get the PIM data for the active document.
    raw_pim_data_string = design.parentDocument.dataFile.assemblyPIMData()
    raw_pim_data: dict = json.loads(raw_pim_data_string)

    for space_id, space in raw_pim_data.items():
        if isinstance(space, dict):
            model_asset: dict = space.get('modelAsset')
            if model_asset:
                f3d_component_id = model_asset['attributes']['f3dComponentId']['value']
                component_wip_lineage_id = model_asset['attributes']['wipLineageUrn']['value']

                if not pim_data.get(component_wip_lineage_id):
                    pim_data[component_wip_lineage_id] = {}
                pim_data[component_wip_lineage_id][f3d_component_id] = space

    return pim_data


def _ensure_file_version_in_results(data_file: adsk.core.DataFile):
    version_id = data_file.versionId
    if not results.get(version_id):
        results[version_id] = _make_design_info(data_file)


def _make_component_info(component, pim_data_for_component_parent_file) -> ComponentInfo:
    return{
        'Name': component.name,
        'f3dComponentId': component.id,
        'ComponentId': _make_fusion_data_component_id(component, pim_data_for_component_parent_file),
        'ComponentVersionId': _make_fusion_data_component_version_id(component, pim_data_for_component_parent_file),
    }


def _make_design_info(data_file: adsk.core.DataFile) -> DesignInfo:
    return {
        'Name': data_file.name,
        'DesignFileId': data_file.id,
        'DesignFileVersionId': data_file.versionId,
        'FolderId': data_file.parentFolder.id,
        'ProjectId': data_file.parentProject.id,
        'HubId': data_file.parentProject.parentHub.id,
        'Components': [],
        'AllComponents': [],
    }


def _get_fresh_file_data_properties(data_file: adsk.core.DataFile) -> dict:
    return {
        'FolderId': data_file.parentFolder.id,
        'ProjectId': data_file.parentProject.id,
        'HubId': data_file.parentProject.parentHub.id,
    }


def _refresh_design_info_result(version_id: str, design_version_info: DesignInfo, data_file: adsk.core.DataFile):
    fresh_file_data = _get_fresh_file_data_properties(data_file)
    design_version_info.update(fresh_file_data)
    results[version_id] = design_version_info
    _write_one_json_object(design_version_info, version_id)


def _get_component_info_from_results_global(version_id: str, component: adsk.fusion.Component) -> ComponentInfo:
    if results.get(version_id, False):
        component_list = results[version_id]['Components']
        component_match = [_component for _component in component_list if _component['f3dComponentId'] == component.id]
        if len(component_match) > 0:
            return component_match[0]


# Does URL safe substitution within python builtin alphabet support
def _make_url_safe_base64_encoded_string(string: str) -> str:
    string_bytes = string.encode("ascii")
    base64_bytes = base64.urlsafe_b64encode(string_bytes)
    base64_string = base64_bytes.decode("ascii")

    # Strip the trailing pad characters
    base64_string = base64_string.rstrip("=")
    return base64_string


def _get_asset_id(space: dict) -> str:
    model_asset: dict = space.get('modelAsset', False)
    if model_asset:
        return model_asset['id']
    return ''


def _get_snapshot_id(space: dict) -> str:
    snapshot_id: str = space.get('snapshotId', False)
    if snapshot_id:
        return snapshot_id
    return ''


def _make_fusion_data_component_id(component: adsk.fusion.Component, pim_data: dict) -> str:
    space: dict = pim_data.get(component.id, None)
    if space:
        pim_model_asset_id = _get_asset_id(space)
        fusion_data_component_id = f'comp~{collection_id}~{pim_model_asset_id}~~'
        return _make_url_safe_base64_encoded_string(fusion_data_component_id)

    return "Failed to get ID"


def _make_fusion_data_component_version_id(component: adsk.fusion.Component, pim_data: dict) -> str:
    space: dict = pim_data.get(component.id, None)
    if space:
        pim_model_asset_id = _get_asset_id(space)
        pim_snapshot_id = _get_snapshot_id(space)
        fusion_data_component_version_id = f'comp~{collection_id}~{pim_model_asset_id}~{pim_snapshot_id}'
        return _make_url_safe_base64_encoded_string(fusion_data_component_version_id)

    return "Failed to get ID"


# File Cache utilities
def _make_design_version_file_name(version_id: str) -> str:
    file_name = version_id.replace(':', '~')
    file_path = os.path.join(json_output_folder, f'{file_name}.json')
    return file_path


def _read_versions_file(version_id: str) -> DesignInfo:
    file_path = _make_design_version_file_name(version_id)
    if os.path.exists(file_path):
        with open(file_path, "r") as infile:
            version_object = json.load(infile)
            return version_object


def _write_results():
    for design_version_id, design_info in results.items():
        _write_one_json_object(design_info, design_version_id)


def _write_one_json_object(design_info: DesignInfo, version_id: str):
    file_path = _make_design_version_file_name(version_id)
    json_string = json.dumps(design_info)
    with open(file_path, "w") as outfile:
        outfile.write(json_string)
