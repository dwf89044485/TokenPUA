# TokenPUA

macOS 菜单栏工具，实时显示 Token 额度使用进度，帮你把额度花完不浪费。

---

## 安装

一行命令安装：

```bash
curl -fsSL https://raw.githubusercontent.com/dwf89044485/TokenPUA/master/install.sh -o /tmp/tpua-install.sh && bash /tmp/tpua-install.sh
```

或下载项目后告诉 AI：

> 帮我安装 TokenPUA
>
> 详见项目中的 GUIDE.md

---

## 状态含义

| 图标 | 含义 | 触发条件 |
| --- | --- | --- |
| 🟥 | 加速! | 实际日均 > 目标日均 × 1.3 |
| 🟡 | 稍加速 | 实际日均 > 目标日均 × 1.1 |
| 🟢 | 完美 | 差距在 ±10% 内 |
| 🟡 | 可放缓 | 实际日均 < 目标日均 × 0.9 |
| 🔵 | 省着用 | 实际日均 < 目标日均 × 0.7 |

按工作日（周一至周五）计算 pacing。
