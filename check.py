import json
data = json.load(open('/tmp/ec2_response.json'))
claims = data.get('claims', [])
print(f'Total claims: {len(claims)}')
for i, c in enumerate(claims[:3]):
  print(f'Claim {i} keys: {list(c.keys())}')
  print(f'Claim {i} comparison: {c.get("comparison", "MISSING")}')
