# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""SDD context module.

The module keeps the material of a software project in an embedded seekDB
instance, selects the material that applies to a development task, hands the
result to MiniMax and stores the state of the task in a PowerContext Server.
"""

from sddctx.config import Settings, load_settings
from sddctx.ingest import import_materials
from sddctx.minimax_client import MiniMaxClient, MiniMaxError, MiniMaxResponse
from sddctx.patch import apply_unified_diff, extract_diff, make_unified_diff
from sddctx.retrieve import TaskContext, build_context, select_specs
from sddctx.state import PowerContextClient, TaskState
from sddctx.store import SeekDBStore

__all__ = [
    "MiniMaxClient",
    "MiniMaxError",
    "MiniMaxResponse",
    "PowerContextClient",
    "SeekDBStore",
    "Settings",
    "TaskContext",
    "TaskState",
    "apply_unified_diff",
    "build_context",
    "extract_diff",
    "import_materials",
    "load_settings",
    "make_unified_diff",
    "select_specs",
]
