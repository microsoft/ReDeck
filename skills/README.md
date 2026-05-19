# ReDeck Claude Code Skill

This directory contains the standalone ReDeck skill for Claude Code.

`redeck.md` teaches Claude Code to generate and repair HTML slides with a render-grounded edit-verify loop. It embeds a Playwright-based `verify_layout` tool that renders each slide, extracts DOM geometry, and reports spatial issues such as overlap, overflow, out-of-bounds content, clipping, low contrast, and broken images.

## Usage

Install the skill by copying `redeck.md` into your Claude Code skills directory. On first use, follow the setup command in the skill to install Playwright and create the local layout verification script.

Typical requests:

- Generate slides from a paper or document
- Check HTML slides for layout issues
- Repair existing HTML slides until layout verification is clean

The intended workflow is simple: design slides boldly, run `verify_layout` after each edit, and keep repairing until the rendered slide has no spatial defects.
