"""Thin orchestration for program planning and prompt rendering."""

from dataclasses import replace

from redeck_style.planning import build_content_profile, build_deck_plan, SlideProgramPlanner
from redeck_style.rendering import render_prompt
from redeck_style.validation import validate_program
from redeck_style.domain.density import density_policy
from redeck_style.domain.asset_presentation import asset_presentation, validate_asset_policy


class ProgramPipeline:
    def __init__(self, library, theme, slides, figures=None, seed=42, dialect_id=None, style_archetype=None,
                 information_density="balanced", asset_mode="auto", asset_policy=None, selected_slide_ids=None):
        density_policy(information_density, "context")
        self.library = library
        self.theme = theme
        self.slides = slides
        self.figures = figures or {}
        asset_policy = {} if asset_policy is None else asset_policy
        validate_asset_policy(asset_mode, asset_policy, self.figures)
        selected = {slide["slide_id"] for slide in slides} if selected_slide_ids is None else set(selected_slide_ids)
        self.asset_presentations = {
            slide["slide_id"]: {**asset_presentation(
                slide, self.figures, asset_mode if slide["slide_id"] in selected else "auto",
                asset_policy if slide["slide_id"] in selected else {},
            ), "selected": slide["slide_id"] in selected}
            for slide in slides
        }
        profiles = [replace(build_content_profile(slide, self.figures),
                            asset_mode=self.asset_presentations[slide["slide_id"]]["mode"])
                    for slide in slides]
        self.deck_plan = build_deck_plan(
            slides, theme, library, seed=seed, dialect_id=dialect_id,
            style_archetype=style_archetype, profiles=profiles,
        )
        planner = SlideProgramPlanner(library, self.deck_plan, information_density=information_density)
        self.programs = planner.plan_deck(profiles)
        for program in self.programs.values():
            validate_program(program, library)

    def prompt_for(self, slide, source_excerpt="", *, include_editorial_policy=True):
        return render_prompt(
            self.programs[slide["slide_id"]],
            self.theme,
            slide,
            self.figures,
            len(self.slides),
            self.library,
            source_excerpt,
            include_editorial_policy=include_editorial_policy,
        )
