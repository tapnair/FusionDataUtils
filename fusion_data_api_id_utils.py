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
from typing import TypedDict
import adsk.core
import adsk.fusion


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


app = adsk.core.Application.get()
ui = app.userInterface

results = {}

collection_id = app.data.activeSpaceCollectionId


def get_fusion_data_ids_for_component(component: adsk.fusion.Component) -> ComponentInfo:
    """
    Returns the relevant Fusion Data API information for the given Component.
    The results are returned as a typed dictionary as described in README.md file.
    """
    component_parent_design = component.parentDesign
    data_file = component_parent_design.parentDocument.dataFile
    version_id = data_file.versionId

    component_result = _get_component_from_results_global(version_id, component)
    if component_result is not None:
        return component_result

    # Try to compute IDs for active design
    _generate_design_version_pim_data(component_parent_design)

    component_result = _get_component_from_results_global(version_id, component)
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
    data_file = design.parentDocument.dataFile
    version_id = data_file.versionId

    # If results already exist return them
    if results.get(version_id, False):
        return results[version_id]

    # Try to compute IDs for active design
    _generate_design_version_pim_data(design)

    # If results already exist return them
    if results.get(version_id, False):
        return results[version_id]

    # Raise an error if IDs could not be computed
    raise RuntimeError(f"Could not get Fusion Data API IDs for: {design.parentDocument.name}")


def _get_component_from_results_global(version_id: str, component: adsk.fusion.Component):
    if results.get(version_id, False):
        component_list = results[version_id]['Components']
        component_match = [_component for _component in component_list if _component['f3dComponentId'] == component.id]
        if len(component_match) > 0:
            return component_match[0]
    return None


# Get relevant PIM data
def _generate_design_version_pim_data(design):
    global collection_id
    collection_id = app.data.activeSpaceCollectionId

    pim_data = _get_pim_data(design)

    data_file = design.parentDocument.dataFile
    _ensure_file_version_in_results(data_file)

    design_version_id = data_file.versionId

    for component in design.allComponents:
        component_data_file = component.parentDesign.parentDocument.dataFile
        _ensure_file_version_in_results(component_data_file)

        component_lineage_id = component_data_file.id
        component_version_id = component_data_file.versionId

        pim_data_for_component_parent_file: dict = pim_data.get(component_lineage_id, None)

        if pim_data_for_component_parent_file:
            # Get Component and ComponentVersion IDs and commit result
            component_object: ComponentInfo = {
                'Name': component.name,
                'f3dComponentId': component.id,
                'ComponentId': _get_component_id(component, pim_data_for_component_parent_file),
                'ComponentVersionId': _get_component_version_id(component, pim_data_for_component_parent_file),
            }
            results[component_version_id]['Components'].append(component_object)
            results[design_version_id]['AllComponents'].append(component_object)


def _ensure_file_version_in_results(data_file: adsk.core.DataFile):
    version_id = data_file.versionId
    if not results.get(version_id, False):
        results[version_id]: DesignInfo = {
            'Name': data_file.name,
            'DesignFileId': data_file.id,
            'DesignFileVersionId': data_file.versionId,
            'FolderId': data_file.parentFolder.id,
            'ProjectId': data_file.parentProject.id,
            'HubId': data_file.parentProject.parentHub.id,
            'Components': [],
            'AllComponents': [],
        }


def _base64_encode(string: str):
    # This would implement the URL alphabet substitutions manually
    # base64_bytes = base64.b64encode(string_bytes)  # Standard encoding alphabet
    # base64_string = base64_bytes.decode("ascii")
    # base64_string = base64_string.replace('+', '-').replace('/', '_').replace('=', '')

    # Does URL safe substitution automatically
    string_bytes = string.encode("ascii")
    base64_bytes = base64.urlsafe_b64encode(string_bytes)
    base64_string = base64_bytes.decode("ascii")

    # Strip the trailing pad characters
    base64_string = base64_string.rstrip("=")

    return base64_string


# Create a map of component.id to Space/Assets
# Component.id is only guaranteed to be unique per file
# Store results grouped by parent files (in the case of a distributed design)
def _get_pim_data(design: adsk.fusion.Design):
    pim_data = {}

    # This is an undocumented API to get the PIM data for the active document.
    raw_pim_data_string = design.parentDocument.dataFile.assemblyPIMData()
    # Data is returned as a json string
    raw_pim_data: dict = json.loads(raw_pim_data_string)

    for key, value in raw_pim_data.items():
        if isinstance(value, dict):
            model_asset: dict = value.get('modelAsset', False)
            if model_asset:
                f3d_component_id = model_asset['attributes']['f3dComponentId']['value']
                component_wip_lineage_id = model_asset['attributes']['wipLineageUrn']['value']
                if not pim_data.get(component_wip_lineage_id, False):
                    pim_data[component_wip_lineage_id] = {}
                pim_data[component_wip_lineage_id][f3d_component_id] = value

    return pim_data


def _get_asset_id(space: dict):
    model_asset = space.get('modelAsset', False)
    if model_asset:
        return model_asset['id']
    return ''


def _get_snapshot_id(space: dict):
    snapshot_id = space.get('snapshotId', False)
    if snapshot_id:
        return snapshot_id
    return ''


def _get_component_id(component: adsk.fusion.Component, pim_data_for_version):
    space: dict = pim_data_for_version.get(component.id, None)
    if space:
        asset_id = _get_asset_id(space)
        pim_id = f'comp~{collection_id}~{asset_id}~~'
        return _base64_encode(pim_id)

    return "Failed to get ID"


def _get_component_version_id(component: adsk.fusion.Component, pim_data):
    space: dict = pim_data.get(component.id, None)
    if space:
        asset_id = _get_asset_id(space)
        snapshot_id = _get_snapshot_id(space)
        pim_id = f'comp~{collection_id}~{asset_id}~{snapshot_id}'
        return _base64_encode(pim_id)

    return "Failed to get ID"
