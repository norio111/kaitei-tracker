# kaitei-tracker Decision Ledger

pt.dbのDecision Ledgerと同じ形式。「なぜその設計をやめたか／選んだか」を、
実データによるObservationとともに残す。番号はpt.db側のD-/O-と衝突しないよう
K-prefixを使う。

---

## K-001: is_admin_relevant()（除外方式）の仮説棄却

**Hypothesis**
type=明確化の項目は事務長にとって重要度が低いため、事務長向けレポートから除外してよい。

**Observation**
`check_admin_excluded.py`で除外項目を目視確認したところ、10件中7件が
「加算」等の収益シグナルを含んでいた。内容も、研修要件・起算日の扱い・
施設基準の調査タイミングなど、既存加算の算定継続可否に実質的に関わるものだった。

**Conclusion**
「type=明確化 は重要度が低い」という仮説は棄却。typeは「変更の形式」を
表すものであり「重要度」ではない。除外方式（Recallリスクを内包する）から、
全件表示＋優先度ランキング方式（`is_admin_priority()`）へ移行した。
旧関数はコード上にコメントアウトで保存し、棄却の記録として残している
（`generate_rehabili_hierarchy.py`末尾）。

---

## K-002: is_admin_priority()の精度確認

**Hypothesis**
type一致 OR is_calculation_decision() OR has_revenue_signal() のOR判定で
「⭐」を付けると、リハビリ領域では診療報酬用語（点・加算）がほぼ全項目に
出現するため識別力を失うのではないか（＝ノイズになるのではないか）。

**Observation**
実データ（26件、⭐23件＝88%）を`check_admin_priority_breakdown.py`で
条件別に分解したところ、⭐のうちtype一致が13件（＝新設/廃止/要件変更/経過措置、
そもそも構造変化なので⭐は妥当）、残る「明確化」13件中10件が⭐、3件が⭐なし。
この⭐あり/なしの内訳は、K-001で人間が目視判定した7件（重要）/3件（重要度低い）
の結果と完全に一致した。

**Conclusion**
仮説（識別力喪失）を棄却。「点」「加算」等の語がほぼ全項目に出現するという
過去の懸念は、旧設計（💰単体で全typeを絞り込む設計）に対するものであり、
今回のOR構造（type一致で大半が説明される中、明確化限定で機能するrevenue_signal）
には当てはまらなかった。現状維持でよいと判断。ただし改定サイクルが変わった際に
再現性があるかは要継続観察。

---

## K-003: Restriction候補の意味論的分類

**Hypothesis**
「算定できない」「対象外」等の否定表現を機械的に拾えば、
`target/condition/effect`の単純な構造を持つrestriction候補が得られるはず。

**Observation**
`find_restriction_candidates.py`で否定表現28件を抽出し目視分類したところ、
以下の3種類が混在していた：
  - Restriction（算定可否そのもの）：約14件
  - Exception（restrictionへの、期限付き等の上位からの適用変更）：約4件
  - CalculationScope / Definition（計算式の定義域・用語範囲。算定可否とは無関係）：約6件

**Conclusion**
否定表現を意味論的な分類軸にすることはできない。判断すべきは
「何に作用しているか」（算定可否／適用条件の変更／計算対象集合／用語定義）
であり、否定語の有無ではない。Restriction単体のSchemaではなく、
Restriction・Exception・CalculationScope・Definitionを区別する必要がある
という方向性を得た。まだSchemaは確定しない。

---

## K-004: 「1 quote = 1 restriction」仮説の棄却

**Hypothesis**
K-003で抽出したRestriction候補14件は、それぞれ1つのrestrictionとして
`target/condition/effect`の3要素に落とし込める。

**Observation**
14件のquoteを人力でatomic単位（1文1主張レベル）まで分解したところ、
23個のatomic statementsに分解された（約1.64倍）。単純な複数化だけでなく、
1つのquote内にRestrictionと非Restriction（肯定的なRequirement、
計算範囲のDefinition、手続き上のObligation）が無差別に同居しているケースが
複数見つかった（例：#7, #13）。

**Conclusion**
「1 quote = 1 restriction」の仮説を棄却。Interpretation層（change_point）と
semantic classification（Restriction/Requirement/Definition/Obligation等）の
間に、atomic statement extraction層が必要である可能性が高い。

**Open Issues**
  - atomic statementの定義（1文1主張、という粒度基準の厳密化）
  - 抽出経路：PDF→atomicか、change_point（既存の抽出結果）→atomicか
  - atomic statement間の関係性（同一quote内での依存・参照関係）
  - Restriction/Requirement等への分類タイミング（atomic抽出と同時か、後段か）

---

## 次のステップ（未着手）

K-004のOpen Issuesのいずれかを実データでさらに検証する。
現時点ではSchemaを設計する段階には至っていない
（pt.dbのStep 0〜6と同型の「実在ケース → Observation → 仮説 → 反証 → 構造化」
の途中、Step 3〜4相当）。
