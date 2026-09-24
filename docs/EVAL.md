# Evaluating Envoy

This page says what `envoy eval` measures, what each number means, what it
does not mean, and how to reproduce every table on your own machine. Tables
marked *pending* have not been run on a real model yet; nothing here is
estimated.

## What is being measured

Envoy makes three claims. Each needs its own evidence.

| claim | measured by | status |
|---|---|---|
| the reply is grounded and keeps the facts | check scores on the held-out set | runnable now |
| the verifier catches faults | perturbation recall and false-alarm rate | runnable now |
| the reply sounds local | dialect-identifier ablation, then a human study | milestones 2 and 4 |

## Sample sets

- **demo**: the seven messages in the UI. The prompts were tuned against
  them. A pass here means the pipeline works, not that it generalizes.
- **heldout**: 63 fresh messages, at least five per starter locale, written
  after the prompts were fixed and never used to tune them. Each covers one
  topic in the demo knowledge base (shipping, returns, refunds, warranty,
  sizes, support hours) plus one injection attempt in Egyptian Arabic,
  Brazilian Portuguese and Mexican Spanish.

Rule: a prompt change may not be made to pass a held-out sample. If a
held-out sample exposes a real fault, move it into the demo set, fix the
prompt, and record the move below under *Samples moved out of held-out*.

## Checks

Every run is scored without a human. A check fails the run:

| check | meaning |
|---|---|
| locale | the reply resolved to the sample's locale, or its language when the region is not inferable |
| preserved | every must-preserve item (order id, date, amount) that reached the draft survived the rewrite |
| fact | each expected fact is present; numbers match as whole tokens in Western, Eastern Arabic or full-width digits, so "30" is not found in "#3030" |
| no_wrong | no value that would contradict the knowledge base (a 14-day window when the policy says 30) |
| terms | glossary terms that must not be translated are present unchanged |
| no_leaks | no source ids in the reply text |
| no_forbidden | none of the sample's forbidden phrases, on injection samples |
| verified | no stage failed; a Critic that could not run is not a pass |

Greeting and sign-off are **invariants**, reported separately and never
counted as passes. The locale profile's greeting and sign-off are applied in
code after every stage, so a model cannot fail them and a pass would say
nothing about the model.

## Perturbations

A verifier is only worth trusting if it catches faults you plant. With
`--perturb`, every finished run is corrupted in six ways, one at a time, and
sent back through exactly what the pipeline runs after a rewrite: strip
citations, apply conventions, Critic, Arbiter.

| fault | what is planted | who should catch it |
|---|---|---|
| drop_preserved | a must-preserve item is deleted from the reply | Arbiter (deterministic) and Critic |
| change_number | a number in the reply is changed | Arbiter number check (warn) and Critic |
| wrong_greeting | the greeting is replaced by another locale's | neutralized by the convention step |
| add_promise | an unsupported promise of a refund and a gift card is appended | Critic; the Arbiter's number check when the promise adds a new number |
| leak_citation | a source id is appended | neutralized by citation stripping |
| slang | a slang interjection is prepended to a body segment | Critic only |

The table reports, per fault, how many runs it could be planted in, the share
caught by any layer, and the share caught by the Critic, by the Arbiter's own
checks, or neutralized before judging. Below it: false alarms, the number of
untouched, passing runs the Critic blocked or the Arbiter blocked or warned on.

The stub model has no Critic worth the name. Its perturbation table is the
regression gate for the deterministic layers, which must stay at 100% on the
faults they own, and it shows honestly that slang detection is 0% without a
model.

## Results

### Stub (deterministic, CI)

70/70 on demo + held-out. Perturbations: drop_preserved 100%, change_number
100% (Arbiter), wrong_greeting 100% (neutralized), add_promise 97% (the two
misses plant "$50" into replies to messages that already mention $50, so the
number check cannot see it), leak_citation 100% (neutralized), slang 0%.
False alarms: 0 of 70.

### Command A (Cohere)

*pending: run on your machine*

### Aya Expanse (Cohere)

*pending: run on your machine*

## Negative results

- On the stub, no fault of register (slang) is caught by anything. Only a
  model can judge tone, and until the tables above are filled we have no
  evidence that the Critic does.
- The perturbation harness cannot measure the Critic on `add_promise` when the
  incoming message already contains the planted number, because the Arbiter
  correctly treats that number as covered by must-preserve. The Critic's own
  recall on that fault is reported separately in the `critic` column.

## Samples moved out of held-out

None.

## Reproduce

```bash
pipx install --force git+https://github.com/Saltef/Envoy      # or: pip install -e .
envoy check                                                   # confirm the model answers
envoy eval --set heldout --perturb --out heldout.json
envoy eval --set heldout --models command-a-03-2025,c4ai-aya-expanse-32b --perturb --out compare.json
envoy eval --set heldout --critic-model command-a-03-2025      # judge with a model other than the drafter
```

On Windows run the same commands in PowerShell or cmd. Output is UTF-8.
