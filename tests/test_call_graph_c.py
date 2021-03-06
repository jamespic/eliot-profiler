import unittest
from .base_call_graph_test import BaseCallGraphTest

try:
    from profilomatic._call_graph import CallGraphRoot

    class CCallGraphTest(BaseCallGraphTest, unittest.TestCase):
        call_graph_class = CallGraphRoot
except ImportError:
    pass
