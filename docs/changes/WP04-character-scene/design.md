# Character scene design and provenance

An original, explicitly adult (26) travel photographer sits within a teal rain-window café, wearing an amber raincoat, dark bob haircut and silver star clip. The illustrated composition uses restrained warm/cool contrast and a quiet editorial type hierarchy, with the scene occupying the main interface. A cup, notebook, lamp and rainy city create continuity without downloading assets.

The original character is inline SVG for independently addressable breathing, eyes/pupils/brows, head, mouth, hands/forearms and camera layers. Four local phases are visually distinct. Calm, warm smile, curious and reflective facial layers are separate geometry; camera lowering and looking toward the window are distinct non-speaking actions. An admitted rain-window event pans/zooms the background and turns the character. The travel artifact reveals only when its media effect is applied.

All SVG geometry and CSS were authored for this project. No external character likeness, sample rig, font, image library or stock asset was used. The coastal travel image is clearly described as an original illustration. The selected multimodal branch is character animation; no runtime image-generation claim is made.

Animation is presentation only. The scene owns no asynchronous queue and cannot release new outputs. Stop prevents talking motion by returning to idle and preserves what was already presented. Actual audio stop and stale callback suppression belong to the integrating audio controller and existing gate.

Accessibility includes labeled input and controls, live plain-text subtitles, local phase descriptions, an accessible character description, decorative art excluded from the accessibility tree, keyboard focus, minimum touch dimensions for main controls, and reduced-motion handling. Responsive code covers 360px and desktop; code-level coverage is not a claim that real mobile browser/audio behavior was tested.
