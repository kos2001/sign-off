"""Optional real-tool fixture generator. Requires klayout Python package."""
import argparse
import klayout.db as db
import klayout.rdb as rdb

parser = argparse.ArgumentParser()
parser.add_argument('output')
args = parser.parse_args()
# A 0.1 x 0.1 um shape intentionally violates a 0.15 um width rule.
region = db.Region(db.Box(0, 0, 100, 100))
markers = region.width_check(150)
assert markers.size() > 0
report = rdb.ReportDatabase('Sign-off width check fixture')
report.top_cell_name = 'TOP'
report.generator = f'KLayout {db.__version__}; width_check(150), dbu=0.001 um'
cell = report.create_cell('TOP')
category = report.create_category('M1.width')
category.description = 'Minimum width 0.15 um; synthetic fixture, not a foundry rule deck'
for marker in markers.each():
    item = report.create_item(cell.rdb_id(), category.rdb_id())
    item.add_value(marker.to_dtype(0.001))
report.save(args.output)
print(f'Generated {markers.size()} real width-check marker items with KLayout {db.__version__}')
