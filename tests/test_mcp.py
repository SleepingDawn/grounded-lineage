import sys
import tempfile
import unittest
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_reader import make_pdf

class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_evidence_and_validation(self):
        params = StdioServerParameters(command=sys.executable, args=['-m', 'scholarly_access_agent', 'mcp-server'])
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / 'fixture.pdf'
            make_pdf(pdf, ['Methods: Training used PBE.', 'References: SCAN paper.'])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    listed = await client.list_tools()
                    names = {t.name for t in listed.tools}
                    self.assertTrue({'read_pdf','doctor','download_pdf'} <= names)
                    download = next(t for t in listed.tools if t.name == 'download_pdf')
                    self.assertNotIn('headless', download.inputSchema['properties'])
                    result = await client.call_tool('read_pdf', {'path':str(pdf),'pages':'2'})
                    self.assertFalse(result.isError)
                    self.assertEqual(result.structuredContent['passages'][0]['page'],2)
                    self.assertIn('References', result.structuredContent['passages'][0]['text'])
                    invalid = await client.call_tool('read_pdf', {'path':str(pdf),'pages':'0'})
                    self.assertTrue(invalid.isError)
                    conflicting = await client.call_tool('read_pdf', {'path':str(pdf),'pages':'2','terms':['SCAN']})
                    self.assertTrue(conflicting.isError)
                    self.assertIn('omit terms', conflicting.content[0].text)
