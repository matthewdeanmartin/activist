# Fixtures

Hand-written sample feeds (RSS 2.0 and Atom) with invented headlines in the
style of clean-energy trade press. All URLs point at `example.com`; none of
the articles are real. Captured/written 2026-06-11.

## The `<activist:hint>` element

A fixture-only affordance (namespace
`https://github.com/matthewdeanmartin/activist/ns`) that lets the
deterministic MockBot produce interesting state transitions without NLP.
Grammar: `key=value; key=value`. Keys:

| key          | meaning                                                        |
|--------------|----------------------------------------------------------------|
| `challenges` | opinion key this article contradicts                           |
| `supports`   | opinion key this article reinforces                            |
| `claim`      | one-sentence claim, quoted into the generated post             |
| `subject`    | short phrase naming the challenger (e.g. "ABC's GW-200")       |
| `new_stance` | the stance to adopt if the bot changes its mind                |

Values must not contain `;`. The OpenRouter engine ignores hints entirely and
works from the article text — real feeds won't have them, and don't need to.

## What the seed fixtures exercise (against the seed `persona/opinions.toml`)

- `cleantechnica-sample.xml` (RSS): a challenge that flips an opinion
  (heat-pump-top-pick, strength 0.8 < 0.85 → changed-my-mind post), a
  reinforcement (used-ev-value), and an off-topic item (filtered out).
- `canarymedia-sample.xml` (Atom): a challenge that fails against high
  conviction (ebike-vs-car, 0.9 → pushback post), a reinforcement
  (induction-stove), and a relevant item with no engaged opinion (abstain —
  the bot is not a summarizer).
- `heatpumped-sample.xml` (RSS): a second heat-pump item that gets paced out
  (one post per opinion key per run), and a reinforcement (beef-biggest-lever).
