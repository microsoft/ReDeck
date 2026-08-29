# B05: Low Contrast - low_contrast

## Focus
Evaluate whether text and information-bearing marks have enough contrast against
their immediate rendered background to be readable at presentation distance.

## Core principle
Readability depends on the foreground/background relationship in the final
pixels: luminance difference, hue separation, saturation, local background
texture, gradients, and image detail all matter.

## Evaluation calibration
Use contrast estimates when available, but also inspect local rendered pixels for
image/gradient/texture backgrounds. Report contrast only when the element's role
requires reading or distinguishing it; muted decoration is not a failure.

## Pass if
1. Normal text has approximately WCAG AA contrast or is plainly readable at
   full-slide scale.
2. Headings, labels, and callouts have sufficient foreground/background
   separation for quick scanning at full-slide scale.
3. Text placed on images, gradients, or colored bands uses overlays, shadows,
   solid backing, or color choices that keep the text legible.
4. Non-text marks that carry information, such as chart lines, data labels,
   icons, and table highlights, remain distinguishable from their background.

## Fail if
1. Text is difficult to read because foreground and background have low luminance
   contrast, regardless of the specific colors used.
2. Text is difficult to read because foreground and background have similar hue
   and saturation, such as tinted text on a similarly tinted panel.
3. Text over an image, chart, gradient, or textured area becomes unreadable in
   some region because the background varies behind it.
4. Secondary but still meaningful text, such as captions, footnotes, axis labels,
   legends, or table notes, falls below readable contrast for its size.
5. Information-bearing chart marks, icons, separators, or emphasis colors are so
   close to the background that the encoded distinction is difficult to see.
6. A repair changes palette or background treatment and leaves formerly readable
   text or labels with noticeably worse contrast.

## Do not flag
1. Muted decorative borders, dividers, shadows, or background tints that do not
   carry information.
2. Medium gray or subdued secondary text that remains readable for its size and
   role.
3. Semantic color choices that are misleading but still readable; use B18.
4. Text that is unreadable because it is too small, clipped, overlapped, or
   blurred rather than because of contrast; use B03, B04, B15, B16, or B17 as
   appropriate.

## Severity
- critical: primary title, key takeaway, main number, or essential chart label
  is nearly invisible or unreadable.
- major: body text or important labels are difficult to read and the slide's
  content requires those elements to understand the message.
- minor: secondary text or marks have marginal contrast but remain decipherable.

## Boundary - use another probe instead
- Color conveys the wrong meaning or inconsistent semantic mapping -> B18
- Text rendering artifacts or corrupted characters -> B11
- Element overlap or occlusion -> B03
- Tiny typography or dense text wall with otherwise adequate contrast -> B16

## Evidence requirements
Identify the element, its role, the approximate foreground and background colors
or background type, and why the contrast fails in the rendered slide. If using a
numeric estimate, cite the approximate contrast ratio; otherwise describe the
visible pixel relationship concretely.
