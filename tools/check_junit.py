"""CI must execute tests, not silently collect or skip them."""
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
cases = list(root.iter("testcase"))
if not cases or any(case.find("skipped") is not None or case.find("failure") is not None
                    or case.find("error") is not None for case in cases):
    raise SystemExit("Quality gate failed: empty, skipped or failing tests")
print(f"Quality gate: {len(cases)} executed tests; no skips/failures/errors")
