#   Copyright (c) 2022 by Autodesk, Inc.
#   Permission to use, copy, modify, and distribute this software in object code form
#   for any purpose and without fee is hereby granted, provided that the above copyright
#   notice appears in all copies and that both that copyright notice and the limited
#   warranty and restricted rights notice below appear in all supporting documentation.
#   AUTODESK PROVIDES THIS PROGRAM "AS IS" AND WITH ALL FAULTS. AUTODESK SPECIFICALLY
#   DISCLAIMS ANY IMPLIED WARRANTY OF MERCHANTABILITY OR FITNESS FOR A PARTICULAR USE.
#   AUTODESK, INC. DOES NOT WARRANT THAT THE OPERATION OF THE PROGRAM WILL BE
#   UNINTERRUPTED OR ERROR FREE.

import json

import adsk.core
import adsk.fusion
import traceback

from .fusion_data_api_id_utils import get_fusion_data_ids_for_active_document, get_fusion_data_ids_for_component

app = adsk.core.Application.get()
ui = app.userInterface


# Print results to text command palette
def run(context):
    try:
        break_string = '************* Assembly Data *************\n'
        app.log(break_string, adsk.core.LogLevels.InfoLogLevel, adsk.core.LogTypes.ConsoleLogType)

        results = get_fusion_data_ids_for_active_document()
        output_string = json.dumps(results, indent=4)
        app.log(output_string, adsk.core.LogLevels.InfoLogLevel, adsk.core.LogTypes.ConsoleLogType)

        adsk.doEvents()

        break_string = '\n\n************* Component Data *************\n'
        app.log(break_string, adsk.core.LogLevels.InfoLogLevel, adsk.core.LogTypes.ConsoleLogType)

        selection = ui.selectEntity('Pick a Component', 'Occurrences,RootComponents')
        if selection.entity.objectType == adsk.fusion.Component.classType():
            component = adsk.fusion.Component.cast(selection.entity)
        elif selection.entity.objectType == adsk.fusion.Occurrence.classType():
            occurrence = adsk.fusion.Occurrence.cast(selection.entity)
            component = occurrence.component
        else:
            raise TypeError('Selection Type was invalid')

        results = get_fusion_data_ids_for_component(component)
        output_string = json.dumps(results, indent=4)
        app.log(output_string, adsk.core.LogLevels.InfoLogLevel, adsk.core.LogTypes.ConsoleLogType)

    except:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
