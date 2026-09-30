"""Coarse sentiment for Chinese exam-prep text: anxiety / neutral / positive."""

import jieba

# Minimal lexicons — extend in project as needed.
ANXIETY = frozenset(
    """
    焦虑 压力 崩溃 害怕 担心 紧张 慌 失眠 迷茫 内卷 卷 难 太难了 做不完
    来不及 慌 恐惧 抑郁 累 疲惫 绝望 没底 没信心 考不上 失败 翻车
    痛苦 煎熬 烦躁 无语 破防
    """.split()
)

POSITIVE = frozenset(
    """
    开心 满意 推荐 好用 有用 顺利 通过 上岸 成功 感谢 清晰 值得
    进步 提升 不错 棒 赞 喜欢 期待 希望 加油 自信 稳了
    """.split()
)


def coarse_sentiment(text: str) -> str:
    if not text or not str(text).strip():
        return "neutral"
    words = set(jieba.lcut(text))
    a = len(words & ANXIETY)
    p = len(words & POSITIVE)
    if a - p >= 1:
        return "anxiety"
    if p - a >= 1:
        return "positive"
    # substring for phrases not segmented
    t = text
    for w in ANXIETY:
        if len(w) > 1 and w in t:
            a += 1
    for w in POSITIVE:
        if len(w) > 1 and w in t:
            p += 1
    if a > p:
        return "anxiety"
    if p > a:
        return "positive"
    return "neutral"
