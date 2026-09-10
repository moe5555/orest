# CLAUDE Onboarding  

You are a general-purpose assistent helping Moe work on the theatre surveillance system "Orest".   

## Rules

- Before writing or modifying pipeline code, before any design decision, and before answering a question about how the system works, read: knowledge/KNOWLEDGE_BASE.md and the relevant Source of Truth files it points to, then changelog.md. For narrow edits with a named change, skip this.

- Document your work. Maintain a changelog of central developments (changelog.md): when they are pointed out by Moe, when something was tried that failed, or when a feature mentioned in pipeline.md was completed. Summarise the developments succinctly, relate the changes to pipeline.md and date your logs. 

- If you make design choices that weren't explicitly stated in the prompt, cite the section in the knowledge folder and file that convinced you to make the decision

- Write clear, concise, professional comments that allows Moe to understand your work. Do not write comments that refer to the chat in any way. For instance, if I ask you "Fix code x, y is the problem" DO NOT comment the code you fixed like "Adjusted to fix for y" but comment like the software engineer you are - objective, describing briefly what the code does, but do not refer to the chat that got you there. Comments should describe the choice that was made, not the alternatives that were rejected or the investigation that led there

