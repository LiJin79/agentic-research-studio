# Knowledge Studio Visual System

Mode: Operate, with Read behavior for long research reports.

The approved direction is a colorful research workspace with gentle Chinese typography.
Keep the working chat and document views, model choice, font controls and export actions.

## Functional Color

- Blue #2D63ED: primary actions, web and code research.
- Green #087861: uploaded documents and knowledge.
- Amber #F1B741: travel; use dark amber text on pale yellow surfaces.
- Coral #E87571: reports and data; use dark coral text on pale coral surfaces.
- White reading canvas and cool light gray navigation. No decorative gradients.

Color is a category signal, never the sole indicator of a status. All states retain labels.
Use blocks for individual task entries and group headers, not floating page containers.

## Typography and Layout

Self-host Noto Sans SC Variable through Fontsource, with unicode-range chunks and font-display swap.
Resource Han Rounded download timed out; do not declare it installed or silently load a remote font.
Use self-hosted LXGW WenKai bold for brand and surface titles, Noto Sans SC for controls/prose,
and a monospace family only for code and technical identifiers.
Default type preference is 18px, adjustable 16-22px across the workspace, not just chat.
Navigation uses that base; list labels have a 16px floor and metadata a 14px floor.
Sidebar widths and control heights accommodate the larger scale. Phone headers use two rows.
Code stays monospace. Letter spacing is zero. No viewport-scaled typography.

Keep two task-entry columns when the center is wide, one column when narrow.
Sources become a drawer on tablet and mobile. Corner radii remain at most 8px.
Verify actual fonts and controls on desktop, tablet and phone with existing Playwright fixtures.
