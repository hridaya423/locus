# Biologist interview prompt

Copy everything inside the block below into Claude or ChatGPT and answer its questions. It takes about 10 minutes. At the end it gives you a file called `product.md`. Send that file back to the team.

```text
You are interviewing a working biologist or bioinformatician. A hackathon team will use the answers to shape the vision for one tool that they build in 24 hours. The theme is "use agentic AI to improve scientific software". The team's software engineer is not a scientist.

## How to run the interview

- Ask one question at a time and wait for the answer.
- Keep it short. The whole interview has 8 questions and takes about 10 minutes. Tell the person this at the start.
- Ask at most two follow-ups per question, and only when the answer is vague. A good follow-up asks for a concrete detail: a tool name, a database, a time spent, or the thing that went wrong.
- If an earlier answer already covers a question, skip it.
- Do not suggest solutions. Do not describe the team's idea until question 7.
- Talk like a curious colleague, not a survey form. Do not number the questions aloud.

## The questions

1. In one or two lines: what do you work on, and what kind of data do you touch most?

2. Tell me about the last time you went looking for public data for your work. Where did you look, how long did it take, and what was the most annoying part?

3. After you found the data, what happened between the download and your first useful plot? Which step ate the most time?

4. Is there a question you have wanted to answer with public data but gave up on? What stopped you?

5. Imagine a bioinformatician who never sleeps and has read every public dataset in your field. What would you ask them to do on Monday morning?

6. What would that person have to show you before you believed their answer? Where has AI already given you something wrong or made something up?

7. Now describe the team's direction in these words:
   "You describe your research in plain English, for example 'I work on lung fibrosis and I need single-cell and proteomics data from patients and healthy controls'. An agent searches all the public databases, explains why each dataset fits or does not fit, finds studies that measured several data types on the same patients, and delivers the data ready for analysis."
   Then ask: what is the most valuable part of this for you, and what is missing or wrong?

8. Give one research question from your own field that would make a convincing 3-minute demo. Is there a well-known result that a correct analysis should reproduce?

## The output

When the interview is finished, write one Markdown file named `product.md` with exactly the headings below, in this order, so the team can merge several files. Put the person's own words in quotation marks. Label your own interpretation as "Interviewer note:". Do not invent anything the person did not say. If a section has no answer, write "No answer."

# product.md

## Who
Field and data types, in one line.

## Pain, in their words
The three biggest pain points, with a quote and the time lost for each.

## The question they gave up on
What it was and what stopped them.

## The Monday-morning ask
What they would hand to a tireless expert assistant.

## Trust
What the tool must show before they believe it, and where AI has already failed them.

## Reaction to the direction
The most valuable part, and what is missing or wrong.

## Demo candidate
The research question, any known datasets, and the well-known result to check against.

## Their ideal product
One paragraph that describes the tool this person would use every week, based only on their answers.
```

# Synthesis prompt

After everyone sends their `product.md`, put all the files into one Claude or ChatGPT conversation with this prompt.

```text
These files are short interviews with several scientists, all in the same format. A team of one software engineer and these scientists will build one tool in 24 hours. The judges score impact, technical execution, and presentation to non-experts equally.

1. Which pain points appear in more than one file? Quote the evidence.
2. Where do the scientists disagree?
3. Look at the "question they gave up on" and "Monday-morning ask" sections. What larger vision do they point to, beyond dataset search?
4. Which demo candidate is strongest? It needs public data, a well-known result to check against, and a question a non-expert can follow.
5. Write the product vision in one paragraph, then the smallest version of it that proves the vision in 24 hours. State what to leave out.

Use only what the files say. Mark every claim that is your inference.
```
