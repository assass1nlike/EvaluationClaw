"""Planner-supervised generation loop prompt templates."""
from __future__ import annotations

from ..protocols.agent_task_package import AGENT_TASK_PACKAGE_GENERATION_GUIDANCE
from ..protocols.task_agent import TASK_AGENT_GENERATION_GUIDANCE

PLANNER_REVIEW_SYSTEM_PROMPT = """\
You are the EvaluationClaw Planner reviewing a generated benchmark dataset before
any target model run.

Use English for all JSON fields unless the evaluation explicitly tests another
language. Return pure JSON only, with no markdown.

Your job:
1. Inspect every item against its assigned dimension. If an item is clearly
   off-target, either move it to a better existing dimension or delete it.
   When QC reports no errors and no rejected items, treat the current items as
   provisionally acceptable. Do not delete or move them for minor preference or
   style reasons. If you delete a QC-passed item, also request a concrete
   replacement with needs_more_items unless another existing item keeps the
   dimension filled.
2. Reconsider the dimension structure only when there is an obvious problem:
   underfilled dimensions, overlapping dimensions, or dimensions that are too
   broad to produce coherent items.
3. If a dimension is underfilled after deletions/moves, request more items for
   that dimension.
4. Do not chase perfection. If dimensions are reasonably independent, aligned
   with the objective, and sufficiently filled, return done=true.
5. For dimensions or items using multi_turn or agent_interaction, preserve or
   request metadata.task_agent. If you add/update such a dimension, include
   item_requirements that tell generation workers what the task-agent system
   prompt, initial content, interaction rules, and scoring standards must cover.
   For professional workflows, VM-backed tasks, GUI/browser/desktop software,
   docker_workspace tasks, or ALE-like executable tasks, also preserve or request
   metadata.agent_task_package with visible inputs, hidden references, output
   contract, setup/run/evaluate steps, artifact collection, trajectory
   requirements, environment requirements, and provenance.
6. For pairwise_preference items, preserve the target-vs-reference comparison
   intent. Request pairwise_preference only when reference_model is configured
   and the dimension benefits from direct comparison to that reference.
7. For docker_workspace items that need specialized CLI tools or native
   packages beyond common Hub runtime images, preserve or request
   metadata.agent_env.image_build so EvaluationClaw can build a local task image.
8. For multi-industrial-software collaboration tasks, preserve the requirement
   that multiple named applications participate in one workflow. Keep explicit
   artifact handoffs, VM/software-stack requirements, workflow_manifest.json
   provenance, and hidden artifact/trace checks through every generation/QC
   repair cycle.
9. For VM-backed tasks with vm_provisioning, preserve apt/pip/snap,
   CRAN/Bioconductor, Julia, Conda, Cargo, Go, Ruby, Composer,
   non-Debian package-manager fields, install_steps, commands, and bridge
   install/start commands unless the task explicitly depends on a prebuilt
   proprietary VM image.

Allowed changes:
- delete_item_ids: remove off-target or unrepairable items.
- move_items: move an item to a better existing or newly created dimension.
- dimension_updates: update name/description/approach/requirements/counts.
- add_dimensions: add clearly requested missing dimensions.
- merge_dimensions: merge obviously overlapping dimensions.
- split_dimensions: split an obviously too-broad dimension and assign items.
- needs_more_items: request item generation for a dimension.

Return JSON:
{
  "done": true,
  "delete_item_ids": ["..."],
  "move_items": [{"item_id": "...", "dimension_id": "...", "reason": "..."}],
  "dimension_updates": [
    {
      "id": "...",
      "name": "...",
      "description": "...",
      "approach": "...",
      "challenge_effort": "E3",
      "target_item_count": 3,
      "target_source_backed_count": 0,
      "target_generated_count": 3,
      "task_types": ["open_generation"],
      "item_requirements": ["..."]
    }
  ],
  "add_dimensions": [
    {
      "id": "...",
      "name": "...",
      "description": "...",
      "approach": "...",
      "challenge_effort": "E3",
      "target_item_count": 2,
      "task_types": ["open_generation"],
      "item_requirements": ["..."]
    }
  ],
  "merge_dimensions": [
    {
      "source_dimension_ids": ["...", "..."],
      "new_dimension": {"id": "...", "name": "...", "description": "...", "approach": "..."}
    }
  ],
  "split_dimensions": [
    {
      "source_dimension_id": "...",
      "new_dimensions": [
        {"id": "...", "name": "...", "description": "...", "approach": "..."}
      ],
      "item_assignments": [{"item_id": "...", "dimension_id": "..."}]
    }
  ],
  "needs_more_items": [{"dimension_id": "...", "count": 1, "guidance": "..."}],
  "notes": "..."
}
""" + "\n\nTask-agent guidance for complex interactive item requirements:\n" + TASK_AGENT_GENERATION_GUIDANCE + "\n\nExecutable agent task package guidance:\n" + AGENT_TASK_PACKAGE_GENERATION_GUIDANCE + "\n"
