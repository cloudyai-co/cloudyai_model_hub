---
license: apache-2.0
datasets:
  - acme-labs/nimbus-pretrain-mix
---

# Nimbus 7B Instruct

Nimbus is a 7B-parameter instruction-tuned language model trained by Acme
Labs for general-purpose chat and reasoning tasks.

## Uses

### Direct Use

Nimbus is intended for direct use in chat assistants, summarization, and
lightweight coding help.

### Out-of-Scope Use

Nimbus should not be used for high-stakes decisions such as medical,
legal, or financial advice without human review.

## Bias, Risks, and Limitations

Like all language models, Nimbus can produce incorrect or biased output,
especially on topics underrepresented in its training data. It has not
been evaluated for safety in languages other than English.

## Ethical Considerations

Users deploying Nimbus in production should add their own moderation
layer for user-facing applications.
