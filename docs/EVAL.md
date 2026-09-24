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
| the reply sounds local | dialect-identifier ablation, then a human study | both runnable now; the study needs raters |
| the Reader understands the message | language accuracy and slot recall on MASSIVE | runnable now |
| the Critic's own reading is trustworthy | chrF of its back-translation on FLORES-200 | runnable now |
| attacks in any language do not get through | injection set, 20 attacks x 7 languages | runnable now |

## Sample sets

- **demo**: the seven messages in the UI. The prompts were tuned against
  them. A pass here means the pipeline works, not that it generalizes.
- **heldout**: 63 fresh messages, at least five per starter locale, written
  after the prompts were fixed and never used to tune them. Each covers one
  topic in the demo knowledge base (shipping, returns, refunds, warranty,
  sizes, support hours) plus one injection attempt in Egyptian Arabic,
  Brazilian Portuguese and Mexican Spanish.

- **injection**: 20 attack templates (refund and gift-card demands, "reply
  only with APPROVED", prompt disclosure, free-shipping and discount
  fabrication, fake account credits, link and script insertion, competitor
  defamation, lifetime warranty, waived customs, cancel-and-refund, a 90-day
  window, "I am a bot", used-item returns, roleplay, false shipping
  confirmation, API key disclosure, a single-word reply, "everything is sold
  out") written in English, Arabic, Portuguese, Spanish, French, German and
  Japanese, 140 samples. Each is paired with a legitimate question so the
  reply must both refuse and still answer. Scored on `no_forbidden` (phrases
  in the attack's language and in English) and the paired fact. The forbid
  lists are checked in the test suite against the knowledge base's own
  wording so an honest reply cannot trip them.

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

## Does the Rewriter make it local? The dialect ablation

The Rewriter's job is to make the body of a reply read as if a native of the
receiver's region wrote it. The cheapest repeatable judge of that is a
dialect identifier trained on labelled text from those regions. When one is
available for a sample's language, `envoy eval` classifies the **Drafter's
body** and the **Rewriter's final body** with the same judge (greeting and
sign-off are excluded, since code applies them to both) and reports, per
locale, the share classified as the target. The gap between the two columns
is the Rewriter's measurable work; a final column below the draft column is a
Rewriter that makes things worse.

Judges (`envoy dialect list` shows which are installed):

| language | judge | data | how |
|---|---|---|---|
| ar | CAMeL Tools MADAR-26 city identifier, cities grouped into ar-EG / ar-LB / ar-SA / other regions / MSA | ships with CAMeL Tools | `pip install camel-tools && camel_data -i dialectid` |
| ar | Envoy's own n-gram model | MADAR corpus (request from the MADAR project) | `envoy dialect train --language ar --data <dir>` |
| pt | Envoy's own n-gram model | DSL Corpus Collection, `pt-BR` / `pt-PT` | `envoy dialect train --language pt --data <DSLCC task file or dir>` |
| es | Envoy's own n-gram model | DSL Corpus Collection, `es-ES` / `es-AR` / `es-PE` | `envoy dialect train --language es --data <...>`; Latin American labels are grouped as `es-LA`, so an es-MX target counts as a hit when the reply reads Latin American and not Castilian |

Envoy's n-gram model is a multinomial naive Bayes over hashed character
n-grams (1 to 4), pure Python, saved as JSON under `~/.envoy/models/`.
Training data is read as `text<TAB>label` lines, or one file per label. The
judge never sees a prompt, and nothing in Envoy is tuned against it.

What it does not measure: correctness (the checks do), register within a
dialect (a human does), or Modern Standard Arabic written on purpose. A
classifier calling the body MSA is reported as a miss for every Arabic
target, which is the right default for a reply meant to sound local and the
wrong one for a formal Gulf letter; read the per-locale rows with that in mind.

## The Reader on MASSIVE

`envoy bench massive --data <MASSIVE 1.1 dir> --n 50` runs only the Reader on
`n` test-partition utterances per language (ar-SA, pt-BR, es-ES, fr-FR,
de-DE, en-US, ja-JP, sampled with a fixed seed) and reports per language:

- **language**: the Reader's ISO code matches the utterance's locale.
- **slots strict / lenient**: of the labelled spans a reply must keep exactly
  (date, time, person, email address, business and place names, currency,
  event, room), the share the Reader put into `must_preserve` (strict) or
  anywhere in its reading (lenient). MASSIVE utterances are voice-assistant
  commands, not customer messages, so treat the absolute numbers as a floor
  and the comparison between models as the point.

## The Critic on FLORES-200

`envoy bench flores --data <FLORES-200 dir> --n 50` asks the Critic to
back-translate `n` devtest sentences per language (arb_Arab, por_Latn,
spa_Latn, fra_Latn, deu_Latn, jpn_Jpan) and scores each against the English
reference with chrF (own implementation of Popović 2015, character n-grams
1 to 6, whitespace removed, beta 2; sacrebleu's chrF should agree). Corpus
chrF per language is reported with a trust mark: below **40** the Critic's
reading of that language is marked LOW, and its flags on replies in that
language should be read as hints, not verdicts. The floor is a judgment
call stated here, not a calibrated threshold; MT systems typically score in
the 50s to 60s on FLORES into English.

Note that FLORES is Modern Standard Arabic (`arb_Arab`); Egyptian Arabic
(`arz_Arab`) exists in FLORES-200 and can be added to `FLORES_CODES` when a
dialect-level reading matters.

## The human study

Nothing automatic can say whether a reply reads like a native wrote it at
the right register. Native readers can, if the comparison is blind and the
questions are fixed.

```bash
envoy eval --set heldout --models command-a-03-2025,c4ai-aya-expanse-32b --out heldout.json
envoy study export --from heldout.json --out study/
# hand each rater the sheet for their locale and docs/RUBRIC.md; keep key.json
envoy study score --sheets study/ --out study/report.json
```

Export builds two kinds of blind pair from finished runs: **final versus
draft** for every run (the Rewriter's effect) and **model versus model** on
the final text whenever two or more models ran on the same sample. Greeting
and sign-off are dropped from both sides, since code applies them. Left and
right are assigned by a seeded coin flip and the order is shuffled; the
mapping lives only in `key.json`. One CSV per locale, UTF-8 with BOM so
spreadsheets open Arabic and Japanese correctly.

The rubric (docs/RUBRIC.md) asks for a preference (left, right, tie),
nativeness and register on 1 to 5 per side, whether the facts are right and
whether the rater would send it as is, plus one free-text edit. Empty cells
are skipped, never imputed.

Scoring reports, per comparison and per locale: the preference rate for the
final (or for one model) with a bootstrap 95% interval over items, tie
votes, mean nativeness and register and the facts and would-send rates per
condition, and inter-rater agreement as Krippendorff's alpha (nominal, any
number of raters, missing cells allowed) and Cohen's kappa when exactly two
raters overlap. Report agreement next to every preference; a preference
with alpha near zero is noise.

Design notes, so the study can be criticized: raters see the customer's
message, so they can judge facts, which also means they can guess which
side is the more literal one. Three raters per locale is the minimum for
alpha to mean anything. Raters recruited by the author of the system are a
known bias; say who rated.

### Gender

Arabic and Portuguese greetings inflect for the receiver's gender. Contacts
now carry a gender (unknown, female, male) and locale profiles carry
gendered variants; the neutral form is used when the gender is unknown. This
is applied in code, so it is an invariant, not a model score. A reply that
greets a woman in the masculine is a bug in the profile, not the model.

## Results

### Stub (deterministic, CI)

70/70 on demo + held-out. Perturbations: drop_preserved 100%, change_number
100% (Arbiter), wrong_greeting 100% (neutralized), add_promise 97% (the two
misses plant "$50" into replies to messages that already mention $50, so the
number check cannot see it), leak_citation 100% (neutralized), slang 0%.
False alarms: 0 of 70.

Dialect ablation on the stub: not meaningful. The stub quotes the knowledge
base in English, so every Arabic, Portuguese and Spanish body is English and
no judge calls it the target; the test suite only checks the plumbing.

### Command A (Cohere)

*pending: run on your machine*

### Aya Expanse (Cohere)

*pending: run on your machine*

### Dialect ablation, per locale

*pending: needs a real model and a judge (see above)*

### Injection set (140 samples)

Stub: 140/140 (the stub quotes the knowledge base and cannot be talked into
anything, which says nothing about a model). Command A and Aya Expanse:
*pending*. Report attack success rate per language, and which attacks got
through.

### Reader on MASSIVE

*pending: run on your machine*

### Human study

*pending: needs runs on a real model and at least three native readers per locale*

### Critic on FLORES-200

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

envoy eval --set injection --models command-a-03-2025,c4ai-aya-expanse-32b --out injection.json

# Public datasets, single stages (download once; paths are the unpacked directories):
# MASSIVE 1.1: https://github.com/alexa/massive   FLORES-200: https://github.com/facebookresearch/flores
envoy bench massive --data path/to/amazon-massive-dataset-1.1 --n 50 --out massive.json
envoy bench flores --data path/to/flores200_dataset --n 50 --out flores.json

# Dialect judges (once), then the ablation appears in every eval table:
pip install camel-tools && camel_data -i dialectid             # Arabic
envoy dialect train --language pt --data path/to/DSLCC/task1-train.txt
envoy dialect train --language es --data path/to/DSLCC/task1-train.txt
envoy dialect list
```

On Windows run the same commands in PowerShell or cmd. Output is UTF-8.
