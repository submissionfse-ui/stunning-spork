# Quacky: A Self-Contained Tutorial

**Quantitative Analysis of Cloud Access Control Policies**

> *From IAM policies to SMT formulas to regex — how Quacky and ABC work under the hood.*

---

## Table of Contents

1. [The Problem: Who Can Access What?](#chapter-1-the-problem-who-can-access-what)
2. [Cloud Access Control Policies](#chapter-2-cloud-access-control-policies)
3. [Analyzing Policies Formally](#chapter-3-analyzing-policies-formally)
4. [SMT Solving — The Engine Under the Hood](#chapter-4-smt-solving--the-engine-under-the-hood)
5. [From Policy JSON to SMT Formula](#chapter-5-from-policy-json-to-smt-formula)
6. [ABC — Automata-Based Counter](#chapter-6-abc--the-automata-based-counter)
7. [From DFA to Regex](#chapter-7-from-dfa-to-regex)
8. [Action-Bucket Summarization (`-ab`)](#chapter-8-action-bucket-summarization)
9. [Query-Action (`-qa`)](#chapter-9-query-action)
10. [Practical Guide: Running Quacky](#chapter-10-practical-guide-running-quacky)

---

# Chapter 1: The Problem — Who Can Access What?

## 1.1 Why This Matters

Imagine you're a system administrator at a company that stores customer data in Amazon S3 (a cloud storage service). You've written access control policies to protect that data. But policies are complex — they interact with each other, and it's hard to tell at a glance:

- What resources can user Alice actually access?
- Did that policy change make things more or less permissive?
- Are there resources that *nobody* should reach but *someone* can?

These are **hard questions** to answer by reading policies manually, especially when you have dozens or hundreds of them. Quacky solves this by treating policies as **mathematical formulas** and using **automated reasoning** to answer these questions precisely.

## 1.2 The Core Idea

Quacky's approach in one sentence:

> **Translate a policy into a math formula, then use a solver to figure out exactly which (principal, action, resource) combinations are allowed.**

Here's the pipeline at a very high level:

```
Policy JSON  →  SMT Formula  →  ABC Solver  →  Results (count, regex, SAT/UNSAT)
 (input)       (translation)    (solving)        (output)
```

We'll build up to understanding every piece of this pipeline.

---

# Chapter 2: Cloud Access Control Policies

## 2.1 What Is a Policy?

A policy is a JSON document that says *who* can do *what* on *which resources*. In AWS, policies use the **IAM** (Identity and Access Management) framework.

Here's a simple example:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowReadFiles",
            "Effect": "Allow",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::mybucket/*"
        }
    ]
}
```

This says: **Allow** anyone to perform the `s3:GetObject` action (reading a file) on any object inside `mybucket`.

## 2.2 The Building Blocks

Every statement in a policy has these key fields:

| Field | What It Means | Example |
|-------|---------------|---------|
| **Effect** | `Allow` or `Deny` | `"Allow"` |
| **Principal** | Who (which user/role/account) | `"*"` (everyone) |
| **Action** | What operation | `"s3:GetObject"` |
| **Resource** | Which cloud object | `"arn:aws:s3:::mybucket/*"` |
| **Condition** | Extra constraints | `"StringEquals": {"aws:userId": "AIDAEXAMPLE"}` |

There are also **negated** versions:
- `NotPrincipal` = everyone *except* these
- `NotAction` = every action *except* these
- `NotResource` = every resource *except* these

## 2.3 Allow vs. Deny

AWS evaluates policies using **deny-overrides**:

1. Check all statements
2. If **any** statement says **Deny** and matches → **DENIED** (no matter what)
3. If **any** statement says **Allow** and matches → **ALLOWED**
4. Otherwise → **DENIED** (implicit deny)

This means: **Deny always wins**. This is critical for understanding how Quacky models policies.

## 2.4 Wildcards

Actions and resources can use wildcards:
- `s3:*` means "any S3 action"
- `arn:aws:s3:::mybucket/*` means "any object in mybucket"
- `*` means "everything"
- `iam:*AccessKey*` means "any IAM action containing 'AccessKey'"

## 2.5 A Realistic Example

Here's a policy with multiple Allow statements and Deny overrides:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowServices",
            "Effect": "Allow",
            "Action": ["s3:*", "cloudwatch:*", "ec2:*"],
            "Resource": "*"
        },
        {
            "Sid": "AllowIAMConsoleForCredentials",
            "Effect": "Allow",
            "Action": ["iam:ListUsers", "iam:GetAccountPasswordPolicy"],
            "Resource": "*"
        },
        {
            "Sid": "DenyS3Logs",
            "Effect": "Deny",
            "Action": "s3:*",
            "Resource": ["arn:aws:s3:::logs", "arn:aws:s3:::logs/*"]
        },
        {
            "Sid": "DenyEC2Production",
            "Effect": "Deny",
            "Action": "ec2:*",
            "Resource": "arn:aws:ec2:*:*:instance/i-1234567890abcdef0"
        }
    ]
}
```

Reading this carefully:
- `AllowServices` allows `s3:*`, `cloudwatch:*`, `ec2:*` on **all** resources
- `DenyS3Logs` blocks all S3 operations on the `logs` bucket
- `DenyEC2Production` blocks all EC2 operations on one specific instance
- Net effect: you can use S3 on everything *except* the logs bucket, EC2 on everything *except* the production instance, and CloudWatch on everything

Figuring this out manually is doable for this small policy. But what if you have 50 statements? That's where Quacky comes in.

---

# Chapter 3: Analyzing Policies Formally

## 3.1 Let's Evaluate a Request by Hand

Before we get into any formal models, let's see how a human would evaluate a policy. Take the policy from Section 2.5 (the one with `AllowServices`, `DenyS3Logs`, etc.) and consider three requests:

### Request A: Alice does `s3:GetObject` on `arn:aws:s3:::photos/cat.jpg`

We check every statement:

| Statement | Matches? | Why? |
|-----------|----------|------|
| AllowServices | ✅ Action `s3:GetObject` matches `s3:*`. Resource `photos/cat.jpg` matches `*`. | **ALLOW** |
| AllowIAMConsoleForCredentials | ❌ Action `s3:GetObject` ≠ `iam:ListUsers` or `iam:GetAccountPasswordPolicy` | skip |
| DenyS3Logs | ❌ Resource `photos/cat.jpg` ≠ `logs` or `logs/*` | skip |
| DenyEC2Production | ❌ Action `s3:GetObject` doesn't match `ec2:*` | skip |

**Result: ALLOWED** ✅ — One Allow matched, no Deny matched.

### Request B: Alice does `s3:PutObject` on `arn:aws:s3:::logs/secret.txt`

| Statement | Matches? | Why? |
|-----------|----------|------|
| AllowServices | ✅ `s3:PutObject` matches `s3:*`, `logs/secret.txt` matches `*` | **ALLOW** |
| DenyS3Logs | ✅ `s3:PutObject` matches `s3:*`, `logs/secret.txt` matches `logs/*` | **DENY** |

**Result: DENIED** ❌ — Even though AllowServices matches, DenyS3Logs also matches. **Deny always wins.**

### Request C: Alice does `iam:CreateUser` on `arn:aws:iam::123456:user/bob`

| Statement | Matches? | Why? |
|-----------|----------|------|
| AllowServices | ❌ `iam:CreateUser` doesn't match `s3:*`, `cloudwatch:*`, or `ec2:*` | skip |
| AllowIAMConsoleForCredentials | ❌ `iam:CreateUser` ≠ `iam:ListUsers` or `iam:GetAccountPasswordPolicy` | skip |
| DenyS3Logs | ❌ | skip |
| DenyEC2Production | ❌ | skip |

**Result: DENIED** ❌ — No statement matched at all. This is an **implicit deny** (also called "neutral").

### The Key Insight

Notice the three possible outcomes: **Allow**, **Deny**, and **Neutral** (implicit deny). Deny and Neutral both result in access being denied, but they're semantically different — Deny means "explicitly blocked", Neutral means "nobody said yes."

This hand-evaluation process is exactly what Quacky automates. But instead of checking one request at a time, Quacky checks **all possible requests simultaneously** using math.

## 3.2 What Questions Can Quacky Answer?

### Question 1: Satisfiability (SAT/UNSAT)
"Is there *any* (principal, action, resource) triple that this policy allows?"

- **SAT** = yes, at least one request is allowed
- **UNSAT** = no, everything is denied

### Question 2: Counting
"How *many* request tuples does this policy allow?"

This gives a quantitative measure of permissiveness. A policy that allows 2^1000 tuples is far more permissive than one that allows 2^10.

### Question 3: Policy Comparison
"Given Policy 1 and Policy 2, are there requests that P1 allows but P2 doesn't?"

This is essential for detecting whether a policy change made things more or less permissive.

## 3.3 The Formal Model

Now let's formalize what we did by hand. Quacky models a policy as a function:

```
policy(principal, action, resource) → {Allow, Deny, Neutral}
```

For each statement `s`, we check if the request matches on **all three dimensions**:
```
s.matches(p, a, r) = s.principal_matches(p) ∧ s.action_matches(a) ∧ s.resource_matches(r)
```

Think of this as the AND in our table above — a statement only fires if the action AND resource (AND principal) all match.

The overall policy combines all statements using deny-overrides:
```
allows = (¬denies) ∧ (s0.allows ∨ s1.allows ∨ ... ∨ sN.allows)
denies = s0.denies ∨ s1.denies ∨ ... ∨ sN.denies
neutral = (¬allows) ∧ (¬denies)
```

Read this as:
- **allows**: "nobody denied it AND at least one statement said yes"
- **denies**: "at least one Deny statement matched"
- **neutral**: "nobody said anything at all"

This is exactly what Quacky translates into SMT.

## 3.4 Exercises

1. Using the policy from Section 2.5, evaluate: Alice does `ec2:TerminateInstances` on `arn:aws:ec2:us-east-1:123456:instance/i-1234567890abcdef0`. What is the result?

2. Same policy: Alice does `cloudwatch:GetMetricData` on `arn:aws:cloudwatch:us-east-1:123456:alarm/MyAlarm`. What is the result? Why?

3. Can you find a request that is *Neutral* (no statement matches at all)? Hint: think of a service not mentioned in the policy.

---

# Chapter 4: SMT Solving — The Engine Under the Hood

## 4.1 Why Not Just Write a Python Script?

You might be thinking: "Why do we need a solver? Can't I just write a `for` loop that checks every request?"

Let's see why that doesn't work.

A request is a triple `(principal, action, resource)` where each is a string. AWS actions are strings like `s3:GetObject` — there are roughly **15,000+** distinct AWS actions. Resource ARNs can be arbitrary strings up to 2048 characters. Principals can be any AWS account ID, user ARN, or role ARN.

Even if we only consider:
- 10 principals
- 15,000 actions
- 1,000 resources

That's **150 million** combinations to check. And that's a massive undercount — resources use wildcards like `arn:aws:s3:::mybucket/*`, which represents an **infinite** set of strings.

**The fundamental problem**: wildcards make the sets of matching strings infinite. You can't enumerate them. You need a tool that reasons about **sets of strings** symbolically — and that's exactly what SMT solvers do.

### What an SMT Solver Does Differently

Instead of checking individual strings, an SMT solver works with **constraints on strings**:

```
"Is there ANY string that starts with 'arn:aws:s3:::logs/'
 AND matches the pattern 's3:*'
 AND is NOT in the set {arn:aws:s3:::backup/*}?"
```

It answers this in milliseconds by manipulating the constraints mathematically, without ever generating a single concrete string.

## 4.2 What Is SMT?

**SMT** stands for **Satisfiability Modulo Theories**. Let's break that down:

- **Satisfiability**: "Can this formula be satisfied?" i.e., is there an assignment of values that makes it true?
- **Modulo Theories**: "...using rules about specific data types" — like strings, integers, or regular expressions.

Think of it like a super-powered equation solver, but instead of just numbers, it works with strings, booleans, regular expressions, and more.

### A Simple Example (Integers)

Variables: `x` (integer), `y` (integer)

Formula: `x + y = 10 ∧ x > 3 ∧ y > 3`

Question: Is there an assignment that satisfies this?

Answer: **SAT** — for example, `x = 5, y = 5`.

### A String Example (Closer to What We Need)

Variables: `action` (string), `resource` (string)

Formula:
```
action starts with "s3:"
AND resource starts with "arn:aws:s3:::mybucket/"
AND resource ≠ "arn:aws:s3:::mybucket/secret.txt"
```

Answer: **SAT** — for example, `action = "s3:getobject"`, `resource = "arn:aws:s3:::mybucket/photo.jpg"`.

This is essentially what Quacky asks: "Is there a request that this policy allows?"

## 4.3 SMT-LIB: The Standard Language

SMT solvers use a standard language called **SMT-LIB**. Here's what it looks like:

```smt2
(set-logic ALL)                          ; Use all theories (strings, booleans, etc.)
(set-option :produce-models true)        ; If SAT, give me an example solution

(declare-const x Int)                    ; Declare: x is an integer variable
(declare-const y Int)                    ; Declare: y is an integer variable

(assert (= (+ x y) 10))                 ; Constraint 1: x + y = 10
(assert (> x 3))                         ; Constraint 2: x > 3
(assert (> y 3))                         ; Constraint 3: y > 3

(check-sat)                              ; Question: can all 3 constraints be true?
(get-model)                              ; If yes, show me values that work
```

Don't be intimidated by the parentheses. Key syntax:
- Everything is in **prefix notation**: `(+ x y)` means `x + y`, `(> x 3)` means `x > 3`
- `(declare-const name Type)` creates a variable
- `(assert ...)` adds a constraint ("this must be true")
- `(check-sat)` asks "is there a solution?"

## 4.4 String Constraints in SMT-LIB

For policy analysis, we need string operations. Here are the critical ones:

```smt2
; Exact match: action must equal "s3:getobject"
(= action "s3:getobject")

; Regex match: action must match the pattern s3:* (s3: followed by anything)
(str.in.re action (re.++ (str.to.re "s3:") (re.* re.allchar)))
;                   └─ string is in this regex ─┘
;                        └─ "s3:" then any characters ─┘
```

Let's decode the regex syntax:
- `(str.to.re "s3:")` = the literal string "s3:" as a regex
- `re.allchar` = match any single character (like `.` in normal regex)
- `(re.* ...)` = zero or more repetitions (like `*` in normal regex)
- `(re.++ A B)` = concatenation: A followed by B

So `(re.++ (str.to.re "s3:") (re.* re.allchar))` means `s3:.*` — "s3:" followed by anything.

## 4.5 Boolean Logic Recap

Quacky uses boolean variables to track whether each statement matches. Quick refresher:

| Operation | SMT-LIB | Plain English | Example |
|-----------|---------|---------------|---------|
| AND | `(and A B)` | Both must be true | "action matches AND resource matches" |
| OR | `(or A B)` | At least one true | "statement 0 allows OR statement 1 allows" |
| NOT | `(not A)` | Must be false | "NOT denied" |

## 4.6 Exercises

1. Write an SMT-LIB formula (just the `assert` lines) for: "x is a string that starts with 'hello' and has length at most 10."

2. In the regex `(re.++ (str.to.re "arn:aws:s3:::") (re.* re.allchar))`, what strings does this match? What IAM wildcard pattern does it correspond to?

3. Why can't we use a standard database query (like SQL) to answer "what resources does this policy allow?" Think about what wildcards mean for the search space.

---

# Chapter 5: From Policy JSON to SMT Formula

This chapter traces exactly how Quacky converts a policy into an SMT formula. This is the **frontend** and **backend** of the pipeline.

## 5.1 The Pipeline

```
policy.json
    │
    ▼
┌──────────────────┐
│ frontend.py       │    validate_args() → sanitize_and_wrap()
│ (parse & clean)   │    - Loads JSON, wraps bare strings into lists
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ policy_model.py   │    Policy → Statement → Principal, Action, Resource, Condition
│ (build model)     │    - Each class has a .smt() method
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ backend.py        │    visit_policy_model()
│ (assemble SMT)    │    - Calls .smt() on the tree, assembles header + body + footer
└──────────────────┘
    │
    ▼
output_1.smt2      ←  The final SMT formula file
```

## 5.2 Step-by-Step: A Concrete Example

Let's trace through this simple policy:

```json
{
    "Statement": [
        {
            "Sid": "AllowRead",
            "Effect": "Allow",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::mybucket/*"
        }
    ]
}
```

### Step 1: Frontend — Parse and Sanitize

`sanitize_and_wrap()` processes the policy:
- Wraps bare strings into lists: `"s3:GetObject"` → `["s3:GetObject"]`
- Leaves `Effect` and `Version` unchanged
- Returns the sanitized dict

### Step 2: Backend — Build the Policy Model

`visit_policy_model()` creates a tree of objects:

```
Policy("p0")
  └── Statement("p0.s0")          ← The Allow statement
        ├── Principal("p0.s0.pr")  ← Implicit: no principal → uses null
        ├── Action("p0.s0.a")      ← ["s3:GetObject"]
        └── Resource("p0.s0.r")    ← ["arn:aws:s3:::mybucket/*"]
```

Each node's `.smt()` method generates SMT-LIB code.

### Step 3: Generate SMT

Each class generates its part of the formula. Here's what the final `.smt2` file looks like:

```smt2
; ─── Header ───
(set-logic ALL)
(set-option :produce-models true)

; ─── Declarations ───
(declare-const principal String)       ; ← Static: always declared
(declare-const action String)          ; ← Static: always declared
(declare-const resource String)        ; ← Static: always declared

; ─── Statement p0.s0 ───

; Principal: p0.s0.pr
(declare-const p0.s0.pr Bool)
(assert (= p0.s0.pr (or (= principal "\x00"))))      ; no principal specified

; Action: p0.s0.a
(declare-const p0.s0.a Bool)
(assert (= p0.s0.a (or (= action "s3:getobject"))))  ; exact match, lowercased

; Resource: p0.s0.r
(declare-const p0.s0.r Bool)
(assert (= p0.s0.r (or                               ; wildcard → regex
    (str.in.re resource
        (re.++ (str.to.re "arn:aws:s3:::mybucket/")
               (re.* re.allchar))))))

; Statement: p0.s0  (this is an Allow statement)
(declare-const p0.s0.allows Bool)
(declare-const p0.s0.denies Bool)
(assert (= p0.s0.allows (and p0.s0.pr p0.s0.a p0.s0.r)))   ; allows if ALL match
(assert (not p0.s0.denies))                                   ; this stmt never denies

; ─── Policy p0 ───
(declare-const p0.allows Bool)
(declare-const p0.denies Bool)
(declare-const p0.neutral Bool)

; allows = (¬denies) ∧ (some statement allows)
(assert (= p0.allows (and (not p0.denies) (or p0.s0.allows))))

; denies = (some statement denies)
(assert (= p0.denies (or p0.s0.denies)))

; neutral = neither allows nor denies
(assert (= p0.neutral (and (not p0.allows) (not p0.denies))))

; ─── Footer (ask: does this policy allow something?) ───
(assert p0.allows)
(check-sat)
(get-model)
```

### Reading It Back: How to Trace a Request Through the Formula

The formula above looks complex, but you can read it like a story. Let's trace **Request A** from Chapter 3: `action = "s3:getobject"`, `resource = "arn:aws:s3:::mybucket/photo.jpg"`.

**Line by line:**

1. `p0.s0.pr = (principal = "\x00")` — Is the principal null? Since no principal was specified in the policy, this is always true. ✅

2. `p0.s0.a = (action = "s3:getobject")` — Is the action exactly `s3:getobject`? Yes! ✅

3. `p0.s0.r = resource matches "arn:aws:s3:::mybucket/" + anything` — Does `arn:aws:s3:::mybucket/photo.jpg` start with `arn:aws:s3:::mybucket/`? Yes! ✅

4. `p0.s0.allows = p0.s0.pr AND p0.s0.a AND p0.s0.r` — All three matched → `p0.s0.allows = true` ✅

5. `p0.s0.denies = false` — This is an Allow statement, it never denies.

6. `p0.allows = (NOT p0.denies) AND (p0.s0.allows)` — Not denied AND something allowed → `p0.allows = true` ✅

7. `(assert p0.allows)` — The footer asks: "Can p0.allows be true?" — Yes! ABC returns **SAT**.

Now try tracing **Request C** from Chapter 3 — `action = "iam:createuser"`. At step 2, `"iam:createuser" ≠ "s3:getobject"`, so `p0.s0.a = false`, which makes `p0.s0.allows = false`, which makes `p0.allows = false`. The footer `(assert p0.allows)` can't be satisfied with this specific action... but ABC doesn't check one action — it asks "does ANY assignment work?" and the answer is still SAT (using `action = "s3:getobject"`).

## 5.3 How Deny Overrides Work in SMT

Now let's see what happens with a policy that has both Allow and Deny. Consider:

```json
{
    "Statement": [
        {"Effect": "Allow", "Action": "s3:*", "Resource": "arn:aws:s3:::mybucket/*"},
        {"Effect": "Deny",  "Action": "s3:DeleteObject", "Resource": "arn:aws:s3:::mybucket/*"}
    ]
}
```

The SMT formula gets TWO statements: `p0.s0` (Allow) and `p0.s1` (Deny):

```smt2
; s0 ALLOWS when action matches s3:* AND resource matches mybucket/*
(assert (= p0.s0.allows (and p0.s0.a p0.s0.r)))
(assert (not p0.s0.denies))    ; Allow statement never denies

; s1 DENIES when action = s3:deleteobject AND resource matches mybucket/*
(assert (not p0.s1.allows))    ; Deny statement never allows
(assert (= p0.s1.denies (and p0.s1.a p0.s1.r)))

; Policy: allows if (NOT denied) AND (some Allow matched)
(assert (= p0.allows (and (not p0.denies) (or p0.s0.allows))))
(assert (= p0.denies (or p0.s1.denies)))
```

**Trace for `s3:GetObject` on `mybucket/photo.jpg`:**
- `p0.s0.allows = true` (action matches `s3:*`, resource matches `mybucket/*`)
- `p0.s1.denies = false` (action `s3:getobject` ≠ `s3:deleteobject`)
- `p0.allows = (NOT false) AND true = true` ✅ **ALLOWED**

**Trace for `s3:DeleteObject` on `mybucket/photo.jpg`:**
- `p0.s0.allows = true` (action matches `s3:*`)
- `p0.s1.denies = true` (action = `s3:deleteobject`, resource matches)
- `p0.allows = (NOT true) AND true = false` ❌ **DENIED** — Deny overrides!

## 5.4 How Wildcards Become Regex

Quacky uses the `re2smt` module to convert IAM wildcards to SMT-LIB regex:

| Policy Wildcard | What It Means | SMT-LIB Regex |
|-----------------|---------------|---------------|
| `s3:GetObject` | Exact action | `(= action "s3:getobject")` |
| `s3:*` | Any S3 action | `(str.in.re action (re.++ (str.to.re "s3:") (re.* re.allchar)))` |
| `iam:*AccessKey*` | IAM actions containing "AccessKey" | `(str.in.re action (re.++ (re.* re.allchar) (str.to.re "accesskey") (re.* re.allchar)))` |

The conversion rule:
- `*` → `(re.* re.allchar)` — match any number of any characters
- `?` → `re.allchar` — match exactly one character
- literal text → `(str.to.re "text")` — match that exact text
- Multiple parts get concatenated with `(re.++ ... ...)`

## 5.5 Two-Policy Comparison

When comparing Policy 1 vs Policy 2, the footer changes. Instead of asking "does P1 allow something?", we ask "does P1 allow something that P2 doesn't?"

**Formula 1** (P1 allows but P2 doesn't):
```smt2
(assert p0.allows)                          ; P1 allows this request
(assert (or p1.denies p1.neutral))          ; AND P2 does NOT allow it
(check-sat)
```

If SAT → there exist requests only P1 allows → P1 is more permissive in some cases.

**Formula 2** (P2 allows but P1 doesn't):
```smt2
(assert p1.allows)                          ; P2 allows this request
(assert (or p0.denies p0.neutral))          ; AND P1 does NOT allow it
(check-sat)
```

| Formula 1 | Formula 2 | Conclusion |
|-----------|-----------|------------|
| SAT | SAT | Neither subsumes the other |
| SAT | UNSAT | P1 is strictly more permissive |
| UNSAT | SAT | P2 is strictly more permissive |
| UNSAT | UNSAT | P1 and P2 are equivalent |

## 5.6 Exercises

1. Write the SMT `assert` lines for this statement: `{"Effect": "Deny", "Action": "s3:*", "Resource": "arn:aws:s3:::logs"}`. What boolean variables do you need?

2. Given a policy with 3 Allow statements (s0, s1, s2) and 1 Deny statement (s3), write the `(assert ...)` lines for `p0.allows` and `p0.denies`.

3. Trace through the Deny example: what happens for `s3:PutObject` on `mybucket/config.json`? Is it allowed or denied?

---

# Chapter 6: ABC — The Automata-Based Counter

## 6.1 What Is ABC?

**ABC** (Automata-Based Counter) is the specialized solver that Quacky uses. It can do three things that general-purpose SMT solvers (like Z3) cannot do efficiently:

1. **Check satisfiability** of string constraints (SAT/UNSAT)
2. **Count** the number of satisfying string tuples
3. **Extract a regex** representing all satisfying values for a variable

ABC's secret weapon is **automata** — it converts string constraints into state machines and uses their mathematical properties to count and extract patterns.

## 6.2 DFA — The Building Block

A **Deterministic Finite Automaton (DFA)** is a machine that reads a string character-by-character and decides "accept" or "reject." Think of it as a flowchart for strings.

### Example: Accepting strings that start with "s3:"

```
         's'        '3'        ':'      any char
   ──→ (q0) ────→ (q1) ────→ (q2) ────→ ((q3)) ──┐
                                                    │ any char
                                                    └──┘
```

Let's trace some strings through this DFA:

| Input | Path | Result |
|-------|------|--------|
| `"s3:getobject"` | q0 →s→ q1 →3→ q2 →:→ q3 →g→ q3 →e→ q3 →...→ q3 | ✅ Accept |
| `"s3:"` | q0 →s→ q1 →3→ q2 →:→ q3 | ✅ Accept |
| `"iam:listusers"` | q0 →i→ ❌ (no 'i' transition from q0) | ❌ Reject |
| `"s4:get"` | q0 →s→ q1 →4→ ❌ (no '4' transition from q1) | ❌ Reject |

The **language** of this DFA is: `{all strings starting with "s3:"}` — which is exactly the set of strings matching the IAM wildcard `s3:*`.

### Key Insight

Every string constraint in our SMT formula can be turned into a DFA. The constraint `(str.in.re action (re.++ (str.to.re "s3:") (re.* re.allchar)))` literally *is* the DFA above.

### Combining DFAs

DFAs can be combined using set operations:

| SMT Operation | DFA Operation | Example |
|---------------|---------------|---------|
| `(and A B)` | **Intersection**: accept strings in BOTH | action matches `s3:*` AND `*object` |
| `(or A B)` | **Union**: accept strings in EITHER | action matches `s3:*` OR `ec2:*` |
| `(not A)` | **Complement**: accept strings NOT in A | action does NOT match `s3:*` |

ABC systematically turns the SMT formula into a large DFA by combining smaller DFAs using these operations.

## 6.3 Multi-Track DFA (MDFA)

Our policy involves three string variables: `principal`, `action`, `resource`. ABC handles all three simultaneously using a **multi-track** DFA.

Think of it as reading three strings in parallel, one character at a time, stacked vertically:

```
Position:         1    2    3    4    5    6    7    8    ...
─────────────────────────────────────────────────────────────
principal:        *    ε    ε    ε    ε    ε    ε    ε
action:           s    3    :    g    e    t    o    b    ...
resource:         a    r    n    :    a    w    s    :    ...
```

At each position, the MDFA reads a **tuple** of characters `(principal[i], action[i], resource[i])` and transitions to the next state. Shorter strings are padded with `ε` (empty).

The MDFA accepts a tuple `(principal, action, resource)` if and only if the policy allows that request.

## 6.4 Projection — Focusing on One Variable

When we want to know "what resources are allowed?", we need to **project** the 3-track MDFA down to just the resource track.

Projection means: "forget about principal and action — what resource values appear in **any** accepting tuple?"

```
Before projection (3-track):
   Accepts: (alice, s3:getobject, mybucket/a.txt)
            (bob,   s3:putobject, mybucket/b.txt)
            (alice, s3:getobject, mybucket/b.txt)
            ... (millions more)

After projection (resource only):
   Accepts: mybucket/a.txt
            mybucket/b.txt
            ... (all resources that appear in ANY accepting tuple)
```

The result is a single-track DFA whose language is exactly the set of all allowed resources. This DFA is then converted to a regex.

## 6.5 Counting

To answer "how **many** (principal, action, resource) tuples are allowed?", ABC counts the accepting paths in the MDFA.

Since strings can be infinitely long, we set a **bound** on the maximum string length. With `-bs 100`, ABC counts all tuples where each string has at most 100 characters.

The count is reported as a raw number, but since it can be astronomically large (like 10^300), Quacky displays it as a **log₂** value:

```
lg(requests): 1400.01    ← means 2^1400 ≈ 10^421 tuples are allowed
```

## 6.6 How ABC Is Invoked

Quacky invokes ABC as a command-line tool:

```bash
abc -bs 100 -v 0 -i output_1.smt2 --precise --count-tuple
```

| Flag | Meaning |
|------|---------|
| `-bs 100` | Bound strings to 100 characters max |
| `-v 0` | Verbosity level 0 (minimal output) |
| `-i output_1.smt2` | Input SMT formula file |
| `--precise` | Use precise counting (not approximate) |
| `--count-tuple` | Count full (principal, action, resource) tuples |

ABC output (on stderr):
```
report is_sat: sat time: 15.23 ms
report (TUPLE) bound: 100 count: 340282366920938463 time: 5.67 ms
```

Quacky parses this output using `get_abc_result_line()` in `utilities.py`.

## 6.7 Exercises

1. Draw a DFA (states + transitions) that accepts exactly the strings `"allow"` and `"deny"`. How many states do you need?

2. You have a DFA for `s3:*` and a DFA for `*object`. If you intersect them, what strings does the result accept? Give 3 examples.

3. Why is projection important? What would happen if we skipped projection and tried to extract a regex from the 3-track MDFA directly?

---

# Chapter 7: From DFA to Regex

## 7.1 Why Regex?

A DFA tells you *which strings are accepted*, but it's not human-readable. A **regular expression** (regex) is equivalent in power but much more understandable:

- DFA with 50 states and 200 transitions → hard to read
- Regex `arn:aws:s3:::mybucket(/.*)?` → immediately clear

So ABC can convert its solution DFA into a regex.

## 7.2 The `--print-regex` Flag

When you add `--print-regex resource` to the ABC command:

```bash
abc -bs 100 -v 0 -i output_1.smt2 --precise --count-tuple --print-regex resource
```

ABC performs these steps:

1. **Solve** the full MDFA (principal × action × resource)
2. **Project** onto the `resource` variable — this removes the principal and action tracks, giving a single-track DFA that accepts exactly the resource strings allowed by the policy
3. **Intersect** with printable ASCII `[ -~]*` (to filter out non-printable characters)
4. **Convert DFA → regex** using the state elimination algorithm (`DFAToRE()`)

The result appears on stderr:
```
report regex_from_dfa: arn:aws:s3:::mybucket(|/(any_printable_char)*)
```

## 7.3 DFA-to-Regex: State Elimination Algorithm

The state elimination algorithm converts a DFA to an equivalent regex by repeatedly removing states. Here's a more realistic example.

### Example: A DFA That Accepts `"ab"` or One-or-More `"b"`s

```
         'a'        'b'
   ──→ (q0) ────→ (q1) ────→ ((q2))
          │
          └──── 'b' ────→ ((q3)) ──┐
                                    │ 'b'
                                    └──┘
```

This DFA accepts: `"ab"`, `"b"`, `"bb"`, `"bbb"`, etc.

**Step 1: Remove q1** (an intermediate state)

q1 has one way in (`q0 →a→ q1`) and one way out (`q1 →b→ q2`). Combine them:
- New transition: `q0 →ab→ q2` (concatenation of 'a' then 'b')

```
         'ab'
   ──→ (q0) ────→ ((q2))
          │
          └──── 'b' ────→ ((q3)) ──┐
                                    │ 'b'
                                    └──┘
```

**Step 2: Read off the regex**

From q0 we can reach:
- q2 via `"ab"` → regex: `ab`
- q3 via `"b"` then zero-or-more `"b"`s → regex: `bb*` (or equivalently `b+`)

Combined: `ab|b+`

### The Three Regex Operations Used

| When you see... | You produce... |
|-----------------|----------------|
| Two transitions in sequence: A → B | **Concatenation**: `AB` |
| Two paths to the same accept state | **Union (OR)**: `A\|B` |
| A self-loop on a state: A → A | **Kleene star**: `A*` |

For complex DFAs with many states, this produces long (but correct) regex strings. A DFA with 50 states might produce a regex with hundreds of characters.

## 7.4 `--print-regex` vs. `--dfa-to-re`

ABC has two flags for regex extraction. Understanding the difference explains the performance trade-off:

| | `--print-regex variable` | `--dfa-to-re variable file alpha omega` |
|---|---|---|
| **What it does** | Projects MDFA → DFA → regex | Same, plus **simplify** and **enumerate** |
| **Internal C++ function** | `Driver::PrintRegex()` | `Driver::GetSimpleRegexes()` |
| **Step 1** | Project to variable | Project to variable |
| **Step 2** | Intersect with printable ASCII | — |
| **Step 3** | `DFAToRE()` (state elimination) | `DFAToRE()` (state elimination) |
| **Step 4** | Output raw regex — done! | `simplify(alpha, omega)` + `enumerate()` |
| **Speed** | **~0.3 seconds** | **5+ minutes** |

The `simplify()` step in `--dfa-to-re` tries to make the regex pretty by grouping characters (e.g., `a|b|c|...|z` → `[a-z]`). This is computationally very expensive — it explores every possible simplification. For our use case (`--print-regex`), the raw verbose regex is good enough.

## 7.5 Exercises

1. Given this DFA that accepts `"cat"` or `"car"`, use state elimination to derive the regex:
   ```
            'c'        'a'        't'
      ──→ (q0) ────→ (q1) ────→ (q2) ────→ ((q3))
                                   │
                                   └── 'r' ──→ ((q4))
   ```

2. Why does `--print-regex` intersect with printable ASCII before converting to regex? What would happen without this step?

3. If a DFA has N states, roughly how complex could the resulting regex be? (Hint: think about what happens during state elimination as N grows.)

---

# Chapter 8: Action-Bucket Summarization

## 8.1 The Problem

Quacky's standard mode tells you: "here's the set of ALL resources the policy allows." But what if you want to know what resources are accessible *per action* or *per group of actions*?

For example, given a policy that allows `s3:*` on `mybucket` and `iam:ListUsers` on `*`, you want:

| Actions | Resources |
|---------|-----------|
| `s3:*` | `arn:aws:s3:::mybucket/*` |
| `iam:ListUsers` | `*` |

This is **action-bucket summarization**.

## 8.2 How It Works

The `-ab` flag in Quacky extracts action-resource pairs by creating per-Allow-statement "buckets":

```
┌──────────────────────────────────────┐
│ Original Policy                       │
│   Allow₁: s3:*        → mybucket/*   │
│   Allow₂: iam:List*   → *            │
│   Deny₁:  s3:Delete*  → mybucket     │
└──────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────┐  ┌────────────────────────┐
│ Bucket 1               │  │ Bucket 2               │
│ (Modified Policy)      │  │ (Modified Policy)      │
│   Allow₁ + Deny₁      │  │   Allow₂ + Deny₁      │
└────────────────────────┘  └────────────────────────┘
         │                           │
         ▼                           ▼
   Full Pipeline              Full Pipeline
   (call_translator +         (call_translator +
    call_abc --print-regex)     call_abc --print-regex)
         │                           │
         ▼                           ▼
   s3:*  → mybucket/*         iam:List* → *
   (minus mybucket due         (Deny₁ doesn't
    to Deny₁)                  affect iam actions)
```

### Key Design Decisions

**Why one bucket per Allow statement?**

Actions within the same Allow statement share the same Resource constraint. You can't get a different resource regex by splitting actions within a single statement, so bucketing by statement is the natural granularity.

**Why include ALL Deny statements in each bucket?**

In AWS, Deny is policy-wide — every Allow must be evaluated against all Denies. A Deny on `s3:Delete*` should subtract from the `s3:*` Allow even if they're in the same bucket.

**Why use subprocess?**

Each bucket runs as a separate `quacky.py` process. This avoids **global state leakage** in `policy_model.py` — the Python module uses global variables (`declarations`, `assertions`, `namespaces`) that accumulate across invocations. Running in a subprocess guarantees a clean slate.

## 8.3 The Code

The implementation lives in `quacky.py` in three functions:

### `extract_action_buckets(policy_json)` — Build the buckets

```python
def extract_action_buckets(policy_json):
    stmts = policy_json.get('Statement', [])
    deny_stmts = [s for s in stmts if s.get('Effect', '').lower() == 'deny']
    buckets = []

    for i, stmt in enumerate(stmts):
        if stmt.get('Effect', '').lower() != 'allow':
            continue

        # Each bucket = this Allow + ALL Deny statements
        modified_policy = copy.deepcopy(policy_json)
        modified_policy['Statement'] = [copy.deepcopy(stmt)] + copy.deepcopy(deny_stmts)
        buckets.append({
            'actions': stmt.get('Action', []),
            'policy': modified_policy,
            ...
        })

    return buckets
```

### `run_action_buckets(args)` — Process each bucket

For each bucket:
1. Write the modified policy to a temp JSON file
2. Run `python3 quacky.py -p1 <temp.json> -b <bound> -s -pr` via subprocess
3. Parse `regex_from_dfa:` from the output
4. Collect and display results

## 8.4 Example Run

```bash
$ python3 quacky.py -p1 multiple_service_access/policy.json -b 100 -s -ab
```

```
======================================================================
Action-Resource Pair Summary
Policy: policy.json
Bound:  100
======================================================================

Found 3 action bucket(s).

  [1/3] AllowServices: s3:*, cloudwatch:*, ec2:*
        → (any_printable_char)* [0.84s]
  [2/3] AllowIAMConsoleForCredentials: iam:ListUsers, iam:GetAccountPasswordPolicy
        → (any_printable_char)* [0.63s]
  [3/3] AllowManageOwnPasswordAndAccessKeys: iam:*AccessKey*, ...
        → arn:aws:iam::*:user/${aws:username} [2.62s]

======================================================================
SUMMARY
======================================================================
#    Actions                                      Resource Regex
----------------------------------------------------------------------
1    s3:*, cloudwatch:*, ec2:*                    *
2    iam:ListUsers, iam:GetAccountPasswordPolicy  *
3    iam:*AccessKey*, iam:ChangePassword, ...     arn:aws:iam::*:user/${aws:username}
======================================================================
Total ABC time: 4.09s
```

Buckets 1 and 2 have `Resource: *` in their Allow statements, so the resource regex is `*` (everything). Bucket 3 has a specific ARN pattern.

---

# Chapter 9: Query-Action

## 9.1 The Problem

Sometimes you want to ask: "For this **specific** action, what resources does the policy allow?"

For example: "What resources can I access with `s3:DeleteBucket`?"

## 9.2 How It Works

The `-qa` flag takes a different approach than action buckets. Instead of modifying the policy JSON, it **injects a constraint directly into the SMT formula**:

```
┌─────────────────┐
│ Original Policy  │
│ (unchanged)      │
└─────────────────┘
        │
        ▼
┌─────────────────┐
│ call_translator  │    Generate the full SMT formula normally
└─────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│ Inject constraint:                       │
│ (assert (= action "s3:deletebucket"))    │    ← Fix the action to exactly this
│ ... right before (check-sat)             │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────┐
│ Run ABC          │    abc --print-regex resource
│                   │    → solve for resource given the fixed action
└─────────────────┘
        │
        ▼
   Resource regex for s3:DeleteBucket
```

### Why This Is Elegant

- **No policy modification** — the original policy JSON stays untouched
- **Full pipeline** — all Conditions, Deny overrides, etc. work correctly
- **Very fast** — ABC only needs to solve for one fixed action (~0.02s vs ~0.3s for a bucket)

## 9.3 The Code

```python
def run_query_action(args):
    action = args.query_action.lower()

    # Step 1: Generate SMT formula via standard pipeline
    call_translator(args)

    # Step 2: Inject action constraint into the .smt2 file
    with open(smt_file, 'r') as f:
        formula = f.read()

    constraint = f'(assert (= action "{action}"))'
    formula = formula.replace('(check-sat)', constraint + '\n(check-sat)')

    with open(smt_file, 'w') as f:
        f.write(formula)

    # Step 3: Run ABC
    cmd = f'abc -bs {bound} -v 0 -i {smt_file} --precise --count-tuple --print-regex resource'
    out, err = shell.runcmd(cmd)
    result = get_abc_result_line(out, err)
```

## 9.4 Example Run

Using a policy where `s3:DeleteBucket` is explicitly denied on `mybucket` but `s3:*` is allowed on `mybucket` and `mybucket/*`:

```bash
# What can s3:GetObject access?
$ python3 quacky.py -p1 s3_allow_all_except_delete/fixed.json -b 100 -s -qa "s3:GetObject"
Action: s3:getobject
Time:   0.02s
Resource regex: arn:aws:s3:::mybucket(|/*)

# What can s3:DeleteBucket access?
$ python3 quacky.py -p1 s3_allow_all_except_delete/fixed.json -b 100 -s -qa "s3:DeleteBucket"
Action: s3:deletebucket
Time:   0.03s
Resource regex: arn:aws:s3:::mybucket/*
```

Notice:
- `s3:GetObject` → can access `mybucket` OR anything inside it (`mybucket/*`)
- `s3:DeleteBucket` → can only access objects *inside* mybucket (`mybucket/*`), not mybucket itself — because the Deny blocks `s3:DeleteBucket` on `mybucket`

This is exactly the expected behavior given the policy's Deny statement.

---

# Chapter 10: Practical Guide — Running Quacky

## 10.1 Prerequisites

- **Python 3**: For the main pipeline
- **ABC**: The SMT solver (must be on PATH as `abc`)
- **Working directory**: All commands should be run from `quacky/src/`

## 10.2 Command Reference

### Basic Analysis (single policy)

```bash
python3 quacky.py -p1 <policy.json> -b <bound> -s
```

| Flag | Required | Description |
|------|----------|-------------|
| `-p1 <file>` | ✅ | Path to the policy JSON |
| `-b <int>` | ✅ | String length bound (usually 100) |
| `-s` | 📌 | Use SMT-LIB syntax (recommended) |
| `-e` | ❌ | Use action encoding |
| `-c` | ❌ | Use resource type constraints |
| `-v` | ❌ | Verbose output |

### Policy Comparison

```bash
python3 quacky.py -p1 <policy1.json> -p2 <policy2.json> -b 100 -s
```

Output tells you whether P1 ⊆ P2, P2 ⊆ P1, or neither.

### Print Resource Regex

```bash
python3 quacky.py -p1 <policy.json> -b 100 -s -pr
```

Adds `regex_from_dfa:` to the output — a regex representing ALL resources the policy allows.

### Action-Bucket Summarization

```bash
python3 quacky.py -p1 <policy.json> -b 100 -s -ab
```

Outputs a table of (actions, resource regex) pairs, one row per Allow statement.

### Query Specific Action

```bash
python3 quacky.py -p1 <policy.json> -b 100 -s -qa "s3:GetObject"
```

Outputs the resource regex for the given specific action.

## 10.3 Output Format

### Standard output:
```
Policy 1
Solve Time (ms): 15.23
satisfiability: sat
Count Time (ms): 5.67
lg(requests): 1400.01
```

- **satisfiability**: `sat` (policy allows something) or `unsat` (denies everything)
- **lg(requests)**: log₂ of the number of allowed (principal, action, resource) tuples
- **regex_from_dfa**: (if `-pr`) the resource regex

## 10.4 Interpreting Regex Output

The raw regex from ABC uses explicit character alternation. For example:

```
(a|b|c|...|z|A|B|...|Z|0|...|9|...)*
```

This is equivalent to `.*` (any string of printable characters). It looks verbose because ABC enumerates every printable ASCII character individually rather than using character classes.

Common patterns:
- `(big_char_alternation)*` = `.*` = any string
- `arn:aws:s3:::mybucket/...` = resources under mybucket
- `arn:aws:s3:::mybucket(|/...)` = mybucket itself OR objects under it

## 10.5 Known Limitations

1. **Cross-service action queries**: Querying an action from a different service (e.g., `ec2:*` against an S3-only policy) may return SAT due to how ABC projects multi-track automata. Results are only reliable when the queried action is within the policy's service scope.

2. **`re2smt` parsing**: Condition values containing `{` (like `${aws:userid}`) may cause parsing errors in `re2smt.py`. This affects some policies with variable interpolation in Conditions.

3. **Regex readability**: ABC's regex output is raw and verbose. The character-by-character alternation (`a|b|c|...|z`) is correct but not human-friendly. A simplification step (like `--dfa-to-re`) produces cleaner output but is much slower (5+ minutes).

---

# Appendix A: Full Architecture Diagram

```
                    ┌─────────────────────────────────────────────┐
                    │                 quacky.py                    │
                    │                                             │
                    │  ┌─── Standard Mode ───┐                    │
                    │  │ call_translator()    │                    │
                    │  │ call_abc()           │                    │
                    │  └─────────────────────┘                    │
                    │                                             │
                    │  ┌─── Action Buckets (-ab) ──────────────┐  │
                    │  │ extract_action_buckets()               │  │
                    │  │ For each bucket:                       │  │
                    │  │   subprocess → quacky.py -pr           │  │
                    │  └───────────────────────────────────────┘  │
                    │                                             │
                    │  ┌─── Query Action (-qa) ────────────────┐  │
                    │  │ call_translator()                      │  │
                    │  │ Inject (assert (= action "..."))       │  │
                    │  │ call_abc() with --print-regex          │  │
                    │  └───────────────────────────────────────┘  │
                    └─────────────────────────────────────────────┘
                                        │
                    ┌───────────────────┼────────────────────┐
                    │                   │                    │
                    ▼                   ▼                    ▼
            ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
            │ frontend.py   │  │ backend.py   │  │ utilities.py      │
            │ - validate    │  │ - visit_     │  │ - header()        │
            │ - sanitize    │  │   policy_    │  │ - footer()        │
            │ - wrap        │  │   model()    │  │ - get_abc_result  │
            └──────────────┘  └──────────────┘  │   _line()         │
                                    │           └──────────────────┘
                                    │
                                    ▼
                            ┌──────────────┐
                            │ policy_      │
                            │   model.py   │
                            │              │
                            │ Policy       │
                            │ └─Statement  │
                            │   ├─Principal│
                            │   ├─Action   │
                            │   ├─Resource │
                            │   └─Condition│
                            └──────────────┘
                                    │
                                    ▼
                            ┌──────────────┐
                            │  .smt2 file  │
                            └──────────────┘
                                    │
                                    ▼
                            ┌──────────────┐
                            │     ABC      │
                            │  (C++ tool)  │
                            │              │
                            │ Parse SMT    │
                            │ Build MDFA   │
                            │ SAT check    │
                            │ Count tuples │
                            │ DFA → Regex  │
                            └──────────────┘
```

# Appendix B: Glossary

| Term | Definition |
|------|------------|
| **ABC** | Automata-Based Counter — the solver Quacky uses for string constraint solving |
| **ARN** | Amazon Resource Name — unique identifier for AWS resources |
| **DFA** | Deterministic Finite Automaton — a state machine that recognizes patterns |
| **IAM** | Identity and Access Management — AWS's access control system |
| **MDFA** | Multi-track DFA — a DFA that reads multiple strings simultaneously |
| **Policy** | A JSON document defining who can do what on which resources |
| **Regex** | Regular Expression — a pattern for matching strings |
| **SAT** | Satisfiable — the formula has at least one solution |
| **SMT** | Satisfiability Modulo Theories — constraint solving over complex types |
| **SMT-LIB** | The standard input language for SMT solvers |
| **UNSAT** | Unsatisfiable — the formula has no solution |
| **Projection** | Removing variables from an automaton to focus on a subset |
| **State Elimination** | Algorithm to convert a DFA into an equivalent regular expression |

---

*This tutorial was written for the FSE-2026 project.*
