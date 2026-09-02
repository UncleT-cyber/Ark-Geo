"""Robotics / OT (ROS) forensics tool modules for the ARK orchestrator.

Each module exposes async ``*_tool`` functions returning honest, structured
dicts with a ``state`` field (``AVAILABLE`` / ``UNAVAILABLE`` / ``ERROR`` /
``TOOL_MISSING``). ROS/OT live introspection wraps the local ROS toolchain
(``rosnode``/``rostopic`` for ROS 1, ``ros2`` for ROS 2) and degrades honestly
when the workspace is not sourced or the tools are absent; safety-config and
parameter-tamper analysis are pure static file parsing.
"""
