#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数和 Kakuro —— 谜题生成器 + 求解器（纯标准库小玩具）

玩法：把 1-9 填进白色格子，要求每一段连续白格（一个 run）里
数字不重复、且加起来等于黑格中的和数线索。

用法：
    python -m kakuro                  # 生成一道 6x6 谜题并打印
    python -m kakuro --seed 42        # 固定种子生成
    python -m kakuro --size 8         # 更大一点的棋盘
    python -m kakuro --solution       # 同时打印答案
    python -m kakuro --save p.txt     # 把谜题存成文本文件
    python -m kakuro --solve p.txt    # 求解文件中的谜题
    python -m kakuro --hint p.txt     # 给一个提示（候选数最少的格子）
    python -m kakuro --selftest       # 内置自检：已知谜题 + 20 个种子
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from itertools import combinations

DIGITS = tuple(range(1, 10))
VERSION = "1.0.0"

__all__ = [
    "Run", "Puzzle", "loads", "dumps", "render",
    "generate", "solve", "verify", "hint", "main",
]


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

class Run:
    """一段连续白格。

    cells: [(r, c), ...] 白格坐标
    total: 和数线索；生成填数阶段可为 None（此时只约束数字不重复）
    clue_cell: 存放线索的黑格坐标
    direction: "right"（横向）或 "down"（纵向）
    """

    __slots__ = ("cells", "total", "clue_cell", "direction")

    def __init__(self, cells, total, clue_cell, direction):
        self.cells = list(cells)
        self.total = total
        self.clue_cell = clue_cell
        self.direction = direction

    def __repr__(self):
        return "Run(%s %s = %s)" % (self.direction, self.cells, self.total)


class Puzzle:
    """一道 Kakuro 谜题。

    size: 棋盘边长（含黑色边框）
    blacks: 黑格坐标集合
    clues: {(r, c): (right_sum|None, down_sum|None)}，只出现在黑格上
    givens: {(r, c): digit} 预填数字（求解时视为已知）
    runs: 自动算出的所有 run
    """

    def __init__(self, size, blacks, clues, givens=None):
        self.size = int(size)
        self.blacks = set(blacks)
        self.clues = {k: (v[0], v[1]) for k, v in clues.items()}
        self.givens = dict(givens or {})
        self.runs = self._compute_runs()

    def _compute_runs(self):
        n = self.size
        blacks = self.blacks
        runs = []
        for r in range(n):
            for c in range(n):
                if (r, c) in blacks:
                    continue
                # 横向 run 的起点：左边是黑格（或棋盘边缘）
                if c == 0 or (r, c - 1) in blacks:
                    cells = []
                    cc = c
                    while cc < n and (r, cc) not in blacks:
                        cells.append((r, cc))
                        cc += 1
                    if len(cells) >= 2:
                        right, _ = self.clues.get((r, c - 1), (None, None))
                        runs.append(Run(cells, right, (r, c - 1), "right"))
                # 纵向 run 的起点：上边是黑格（或棋盘边缘）
                if r == 0 or (r - 1, c) in blacks:
                    cells = []
                    rr = r
                    while rr < n and (rr, c) not in blacks:
                        cells.append((rr, c))
                        rr += 1
                    if len(cells) >= 2:
                        _, down = self.clues.get((r - 1, c), (None, None))
                        runs.append(Run(cells, down, (r - 1, c), "down"))
        return runs

    @property
    def white_cells(self):
        cells = set()
        for run in self.runs:
            cells.update(run.cells)
        return cells

    def clue_count(self):
        return sum(1 for run in self.runs if run.total is not None)


# ---------------------------------------------------------------------------
# 文本格式（--save / --solve 用）
# ---------------------------------------------------------------------------
#
# 第一行是棋盘边长，之后每行 n 个空格分隔的记号：
#   #       黑格（无线索）
#   r16     黑格：横向和数线索 16
#   d7      黑格：纵向和数线索 7
#   r16d7   黑格：两个方向都有线索
#   .       白格（空）
#   5       白格：预填数字 5（求解时视为已知）

_TOKEN_RE = re.compile(r"^r(\d+)(d(\d+))?$|^d(\d+)$")


def loads(text):
    """从文本格式解析出一道谜题。"""
    toks = text.split()
    if not toks:
        raise ValueError("空文件")
    try:
        n = int(toks[0])
    except ValueError:
        raise ValueError("第一行必须是棋盘边长（整数）")
    toks = toks[1:]
    if len(toks) != n * n:
        raise ValueError("记号数量不对：期望 %d 个，实际 %d 个" % (n * n, len(toks)))
    blacks, clues, givens = set(), {}, {}
    it = iter(toks)
    for r in range(n):
        for c in range(n):
            tok = next(it)
            if tok == "#":
                blacks.add((r, c))
            elif tok == ".":
                pass
            elif tok.isdigit() and len(tok) == 1 and tok != "0":
                givens[(r, c)] = int(tok)
            else:
                m = _TOKEN_RE.match(tok)
                if not m:
                    raise ValueError("无法识别的记号：%r（第 %d 行第 %d 列）" % (tok, r + 1, c + 1))
                blacks.add((r, c))
                right = int(m.group(1)) if m.group(1) else None
                down = int(m.group(3)) if m.group(3) else int(m.group(4)) if m.group(4) else None
                clues[(r, c)] = (right, down)
    return Puzzle(n, blacks, clues, givens)


def dumps(puzzle):
    """把谜题序列化成文本格式。"""
    n = puzzle.size
    lines = [str(n)]
    for r in range(n):
        row = []
        for c in range(n):
            if (r, c) in puzzle.blacks:
                right, down = puzzle.clues.get((r, c), (None, None))
                tok = ""
                if right is not None:
                    tok += "r%d" % right
                if down is not None:
                    tok += "d%d" % down
                row.append(tok if tok else "#")
            elif (r, c) in puzzle.givens:
                row.append(str(puzzle.givens[(r, c)]))
            else:
                row.append(".")
        lines.append(" ".join(row))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 漂亮打印（ASCII 表格）
# ---------------------------------------------------------------------------

def _cell_text(puzzle, r, c, solution):
    if (r, c) in puzzle.blacks:
        right, down = puzzle.clues.get((r, c), (None, None))
        if right is None and down is None:
            return "#" * 7
        rs = str(right) if right is not None else ""
        ds = str(down) if down is not None else ""
        return "%3s\\%-3s" % (rs, ds)
    if solution and (r, c) in solution:
        return "   %d   " % solution[(r, c)]
    if (r, c) in puzzle.givens:
        return "   %d   " % puzzle.givens[(r, c)]
    return " " * 7


def render(puzzle, solution=None):
    """把谜题画成 ASCII 表格；solution 可选 {(r, c): digit}。"""
    n = puzzle.size
    bar = "+" + "+".join(["-" * 7] * n) + "+"
    lines = [bar]
    for r in range(n):
        lines.append("|" + "|".join(_cell_text(puzzle, r, c, solution) for c in range(n)) + "|")
        lines.append(bar)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 求解器：带和数可行性剪枝的回溯 + MRV
# ---------------------------------------------------------------------------

class _Solver:
    def __init__(self, puzzle, max_solutions=1, rng=None):
        self.max_solutions = max_solutions
        self.rng = rng
        self.runs = puzzle.runs
        self.cell_runs = {}
        for i, run in enumerate(self.runs):
            for cell in run.cells:
                self.cell_runs.setdefault(cell, []).append(i)
        self.white = sorted(self.cell_runs)
        self.value = {}
        self.used = [set() for _ in self.runs]
        self.left = [run.total for run in self.runs]  # None = 无和数约束
        self.open = [len(run.cells) for run in self.runs]
        self.solutions = []
        self.impossible = False
        for cell, d in sorted(puzzle.givens.items()):
            if not self._try_place(cell, d):
                self.impossible = True
                break

    # -- 候选与剪枝 ------------------------------------------------------
    def _feasible(self, ri, d):
        """假设往 run ri 里放 d，剩下的和数是否还有可能凑出来。"""
        total = self.left[ri]
        if total is None:
            return True
        rest = total - d
        k = self.open[ri] - 1
        if k < 0 or rest < 0:
            return False
        if k == 0:
            return rest == 0
        avail = [x for x in DIGITS if x not in self.used[ri] and x != d]
        if len(avail) < k:
            return False
        if sum(avail[:k]) > rest:      # 最小的 k 个都太大
            return False
        if sum(avail[-k:]) < rest:     # 最大的 k 个都太小
            return False
        return any(sum(c) == rest for c in combinations(avail, k))

    def _candidates(self, cell):
        digits = list(DIGITS)
        if self.rng:
            self.rng.shuffle(digits)
        out = []
        for d in digits:
            ok = True
            for ri in self.cell_runs[cell]:
                if d in self.used[ri] or not self._feasible(ri, d):
                    ok = False
                    break
            if ok:
                out.append(d)
        return out

    # -- 放置 / 撤销 ------------------------------------------------------
    def _try_place(self, cell, d):
        for ri in self.cell_runs[cell]:
            if d in self.used[ri] or not self._feasible(ri, d):
                return False
        self.value[cell] = d
        for ri in self.cell_runs[cell]:
            self.used[ri].add(d)
            self.open[ri] -= 1
            if self.left[ri] is not None:
                self.left[ri] -= d
        return True

    def _unplace(self, cell, d):
        del self.value[cell]
        for ri in self.cell_runs[cell]:
            self.used[ri].discard(d)
            self.open[ri] += 1
            if self.left[ri] is not None:
                self.left[ri] += d

    # -- MRV 回溯 ----------------------------------------------------------
    def _search(self):
        if len(self.solutions) >= self.max_solutions:
            return True  # 够了，停
        best, best_cands = None, None
        for cell in self.white:
            if cell in self.value:
                continue
            cands = self._candidates(cell)
            if not cands:
                return False
            if best_cands is None or len(cands) < len(best_cands):
                best, best_cands = cell, cands
                if len(best_cands) == 1:
                    break
        if best is None:  # 全部填满
            self.solutions.append(dict(self.value))
            return len(self.solutions) >= self.max_solutions
        for d in best_cands:
            self.value[best] = d
            for ri in self.cell_runs[best]:
                self.used[ri].add(d)
                self.open[ri] -= 1
                if self.left[ri] is not None:
                    self.left[ri] -= d
            stop = self._search()
            self._unplace(best, d)
            if stop:
                return True
        return False

    def run(self):
        if not self.impossible:
            self._search()
        return self.solutions


def solve(puzzle, max_solutions=1, seed=None):
    """求解谜题，返回解的列表（每个解是 {(r, c): digit}）。

    max_solutions: 最多找几个解（可用于数解 / 判断唯一性）。
    seed: 给随机数种子则候选数字按随机顺序尝试（用于生成器）。
    """
    rng = random.Random(seed) if seed is not None else None
    return _Solver(puzzle, max_solutions=max_solutions, rng=rng).run()


def verify(puzzle, solution):
    """检查一个填法是否合法，返回问题描述列表（空列表 = 合法）。"""
    errors = []
    for cell in puzzle.white_cells:
        v = solution.get(cell)
        if v not in DIGITS:
            errors.append("格子 %s 没填或数字非法" % (cell,))
    for run in puzzle.runs:
        vals = [solution.get(cell) for cell in run.cells]
        if any(v not in DIGITS for v in vals):
            continue
        if len(set(vals)) != len(vals):
            errors.append("%s run %s 数字重复：%s" % (run.direction, run.cells[0], vals))
        if run.total is not None and sum(vals) != run.total:
            errors.append("%s run %s 和数应为 %d，实际 %d" % (
                run.direction, run.cells[0], run.total, sum(vals)))
    return errors


def hint(puzzle):
    """给一个提示：返回 (r, c, digit, 候选数)，即候选最少的空格及其答案。

    找不到解时返回 None。
    """
    sols = solve(puzzle, max_solutions=1)
    if not sols:
        return None
    answer = sols[0]
    probe = _Solver(puzzle, max_solutions=1)
    if probe.impossible:
        return None
    best = None
    for cell in probe.white:
        if cell in puzzle.givens:
            continue
        cands = probe._candidates(cell)
        if cands and (best is None or len(cands) < len(best[3])):
            best = (cell[0], cell[1], answer[cell], cands)
            if len(cands) == 1:
                break
    return best


# ---------------------------------------------------------------------------
# 生成器
# ---------------------------------------------------------------------------
#
# 思路：先随机画黑格图案（默认 180° 旋转对称，修掉长度 < 2 的 run），
# 再用"无和数约束"的求解器随机填出一组不重复的数字，
# 最后按这组数字算出每个 run 的和数作为线索。
# 因为线索本来就是从一组合法填法反推出来的，谜题必定有解。

def _random_pattern(n, rng, symmetric):
    """随机黑格图案，保证每个白格 run 长度 >= 2。"""
    for _attempt in range(300):
        black = [[True] * n for _ in range(n)]  # 边框全黑
        for r in range(1, n - 1):
            for c in range(1, n - 1):
                if symmetric and (n - 1 - r, n - 1 - c) < (r, c):
                    continue  # 由对称点决定
                v = rng.random() < 0.38
                black[r][c] = v
                if symmetric:
                    black[n - 1 - r][n - 1 - c] = v

        def blacken(r, c):
            black[r][c] = True
            if symmetric:
                black[n - 1 - r][n - 1 - c] = True

        # 修掉长度为 1 的 run（把孤立白格涂黑），直到稳定
        for _ in range(100):
            changed = False
            for r in range(n):  # 横向
                c = 0
                while c < n:
                    if black[r][c]:
                        c += 1
                        continue
                    c2 = c
                    while c2 < n and not black[r][c2]:
                        c2 += 1
                    if c2 - c < 2:
                        blacken(r, c)
                        changed = True
                    c = c2
            for c in range(n):  # 纵向
                r = 0
                while r < n:
                    if black[r][c]:
                        r += 1
                        continue
                    r2 = r
                    while r2 < n and not black[r2][c]:
                        r2 += 1
                    if r2 - r < 2:
                        blacken(r, c)
                        changed = True
                    r = r2
            if not changed:
                break

        blacks = {(r, c) for r in range(n) for c in range(n) if black[r][c]}
        tmp = Puzzle(n, blacks, {})
        white = tmp.white_cells
        # 白格太少就重画（阈值按内部格数折算，小棋盘也留活路）
        if len(white) >= max(4, (n - 2) * (n - 2) * 2 // 5) and len(tmp.runs) >= 4:
            return blacks
    raise RuntimeError("画不出合格的黑格图案（请换种子或调小棋盘）")


def generate(size=6, seed=None, style="symmetric"):
    """生成一道谜题，返回 (puzzle, solution)。

    因为线索是从一组合法填法反推出来的，生成的谜题必定有解；
    但随机图案通常约束不足，不保证唯一解（见 README「局限」）。
    """
    if not 4 <= size <= 10:
        raise ValueError("size 需在 4~10 之间")
    rng = random.Random(seed)
    symmetric = (style == "symmetric")
    while True:
        blacks = _random_pattern(size, rng, symmetric)
        blank = Puzzle(size, blacks, {})  # 无和数约束：只要求数字不重复
        fills = solve(blank, max_solutions=1, seed=rng.randrange(1 << 30))
        if not fills:
            continue  # 极罕见：填不出来就换图案重来
        fill = fills[0]
        clues = {}
        for run in blank.runs:
            total = sum(fill[cell] for cell in run.cells)
            cr, cc = run.clue_cell
            right, down = clues.get((cr, cc), (None, None))
            if run.direction == "right":
                right = total
            else:
                down = total
            clues[(cr, cc)] = (right, down)
        return Puzzle(size, blacks, clues), fill


# ---------------------------------------------------------------------------
# 内置自检：已知谜题（手工验算）+ 20 个种子
# ---------------------------------------------------------------------------

# 4x4 已知谜题。内部 2x2 全白，手工指定的合法填法：
#   1 3
#   4 2
# 横向和数：4、6；纵向和数：5、5。经手工验算每段无重复、和数正确。
KNOWN_TEXT = """\
4
# d5 d5 #
r4 . . #
r6 . . #
# # # #
"""
KNOWN_SOLUTION = {(1, 1): 1, (1, 2): 3, (2, 1): 4, (2, 2): 2}


def selftest():
    """跑全部自检，返回 (通过项, 失败项)。"""
    passed, failed = [], []

    def check(name, fn):
        try:
            fn()
            passed.append(name)
        except AssertionError as e:
            failed.append("%s：%s" % (name, e))

    # 1. 已知谜题：手工答案本身合法，且求解器能解出来、解也合法
    def t_known():
        p = loads(KNOWN_TEXT)
        assert not verify(p, KNOWN_SOLUTION), "手工答案竟不合法：%s" % verify(p, KNOWN_SOLUTION)
        sols = solve(p, max_solutions=4)
        assert sols, "已知谜题无解"
        for s in sols:
            assert not verify(p, s), "求解器的解不合法：%s" % verify(p, s)
    check("已知谜题求解正确", t_known)

    # 2. 20 个种子：生成的谜题全部可解、解合法、run 内无重复数字
    def t_seeds():
        bad = []
        for seed in range(1, 21):
            puzzle, _fill = generate(6, seed=seed)
            sols = solve(puzzle, max_solutions=1)
            if not sols:
                bad.append("seed=%d 无解" % seed)
                continue
            errs = verify(puzzle, sols[0])
            if errs:
                bad.append("seed=%d 解非法：%s" % (seed, errs[:2]))
        assert not bad, "; ".join(bad)
    check("20 个种子全部可解且无重复数字", t_seeds)

    # 3. 文本格式 roundtrip：存盘再读回来，谜题不变、照样能解
    def t_roundtrip():
        puzzle, _fill = generate(6, seed=7)
        p2 = loads(dumps(puzzle))
        assert p2.size == puzzle.size
        assert p2.blacks == puzzle.blacks
        assert p2.clues == puzzle.clues
        sols = solve(p2, max_solutions=1)
        assert sols and not verify(p2, sols[0])
    check("文本格式存取 roundtrip", t_roundtrip)

    # 4. 无解谜题：求解器应返回空列表而不是卡死/报错
    def t_unsolvable():
        p = loads("4\n# d5 d5 #\nr4 . . #\nr6 . . #\n# # # #\n")
        p.clues[(1, 0)] = (50, None)  # 横向和数 50：两格 1-9 不可能凑出
        p.runs = p._compute_runs()
        assert solve(p, max_solutions=1) == [], "不可能的和数应无解"
    check("无解谜题正确返回空", t_unsolvable)

    # 5. 两种图案风格都能生成
    def t_styles():
        for style in ("symmetric", "random"):
            puzzle, _fill = generate(5, seed=3, style=style)
            sols = solve(puzzle, max_solutions=1)
            assert sols and not verify(puzzle, sols[0]), style
    check("symmetric/random 两种风格", t_styles)

    return passed, failed


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def _build_parser():
    ap = argparse.ArgumentParser(
        prog="kakuro",
        description="数和 Kakuro：生成谜题、求解谜题的小玩具（纯标准库）。",
    )
    ap.add_argument("--size", type=int, default=6,
                    help="生成棋盘边长，4~10，默认 6")
    ap.add_argument("--seed", type=int, default=None,
                    help="随机种子；相同种子生成相同谜题")
    ap.add_argument("--style", choices=["symmetric", "random"], default="symmetric",
                    help="黑格图案风格：symmetric=180°旋转对称（默认），random=完全随机")
    ap.add_argument("--save", metavar="文件",
                    help="把生成的谜题存成文本文件")
    ap.add_argument("--solution", action="store_true",
                    help="生成时同时打印答案")
    ap.add_argument("--solve", metavar="文件",
                    help="求解文本文件中的谜题并打印答案")
    ap.add_argument("--hint", metavar="文件",
                    help="给文件中的谜题一个提示（候选数最少的格子）")
    ap.add_argument("--selftest", action="store_true",
                    help="运行内置自检（已知谜题 + 20 个种子）")
    ap.add_argument("--version", action="version", version="kakuro " + VERSION)
    return ap


def main(argv=None):
    ap = _build_parser()
    args = ap.parse_args(argv)

    if args.selftest:
        passed, failed = selftest()
        for name in passed:
            print("  [通过] %s" % name)
        for name in failed:
            print("  [失败] %s" % name)
        print("自检结果：%d 通过，%d 失败" % (len(passed), len(failed)))
        return 1 if failed else 0

    if args.solve:
        try:
            with open(args.solve, encoding="utf-8") as f:
                puzzle = loads(f.read())
        except (OSError, ValueError) as e:
            print("读取谜题失败：%s" % e, file=sys.stderr)
            return 2
        sols = solve(puzzle, max_solutions=2)
        if not sols:
            print("这道题无解（线索可能有矛盾）。")
            return 1
        print(render(puzzle, sols[0]))
        if len(sols) > 1:
            print("注意：这道题不止一个解（至少 %d 个）。" % len(sols))
        else:
            print("（唯一解）")
        return 0

    if args.hint:
        try:
            with open(args.hint, encoding="utf-8") as f:
                puzzle = loads(f.read())
        except (OSError, ValueError) as e:
            print("读取谜题失败：%s" % e, file=sys.stderr)
            return 2
        h = hint(puzzle)
        if h is None:
            print("这道题无解，给不出提示。")
            return 1
        r, c, digit, cands = h
        print("提示：第 %d 行第 %d 列填 %d（该格候选只有 %d 个：%s）" % (
            r + 1, c + 1, digit, len(cands), " ".join(map(str, sorted(cands)))))
        return 0

    # 默认：生成一道新谜题
    try:
        puzzle, solution = generate(args.size, seed=args.seed, style=args.style)
    except (ValueError, RuntimeError) as e:
        print("生成失败：%s" % e, file=sys.stderr)
        return 2

    if args.save:
        try:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(dumps(puzzle))
            print("已保存到 %s" % args.save)
        except OSError as e:
            print("保存失败：%s" % e, file=sys.stderr)
            return 2

    print(render(puzzle, solution if args.solution else None))
    # 顺手探一下解是否唯一（只数到 2，很快），如实告诉用户
    n_solutions = len(solve(puzzle, max_solutions=2))
    tag = "（唯一解）" if n_solutions == 1 else "（有多解，本玩具不保证唯一解）"
    print("白格 %d 个，和数线索 %d 条 %s" % (
        len(puzzle.white_cells), puzzle.clue_count(), tag))
    if args.seed is not None:
        print("种子：%d（用相同种子可复现本题）" % args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
