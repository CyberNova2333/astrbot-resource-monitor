# AstrBot Resource Monitor 独立资产与项目标识许可清单 (`ASSET_LICENSES`)

本清单依据 [AstrBot Resource Monitor AGPLv3 附加条款及资产与项目标识规则](ADDITIONAL_TERMS.zh-CN.md)（英文参考：[ADDITIONAL_TERMS.en.md](ADDITIONAL_TERMS.en.md)）第七条第 7.2 款与第八条设立，用于如实登记仓库中随项目分发的标识图形、界面美术资产、字体及第三方静态视觉/前端资源及其各自适用的有效许可证。

> **说明：** 本清单不以登记方式向已有第三方或开源许可资产追加额外限制；第三方资产仍严格适用其原有有效许可证（SIL OFL 1.1、MIT、Apache-2.0 等）。标注「项目标识：是」且由相应权利人授权随项目提供的默认名称、Logo 与图标，依据 `ADDITIONAL_TERMS.zh-CN.md` 第五条与第八条规范使用（不主张已注册商标专用权）。

| 资产路径 / 名称 | 作者与版权持有人 | 来源 | 适用许可证与版本 / 许可位置 | 是否为项目标识 | 随程序复制、构建、分发与显示授权范围 |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `docs-site/.vitepress/theme/fonts/ibm-plex-sans-latin-*.woff2` | IBM Corp. | IBM Plex Sans（文档站主题自托管字体） | SIL Open Font License 1.1（见 `docs-site/.vitepress/theme/fonts/IBM-Plex-Sans-LICENSE.txt`） | 否 | 随 `docs-site` 静态文档站构建与在线／离线浏览分发 |
| `docs-site/.vitepress/theme/fonts/jetbrains-mono-latin-500-normal.woff2` | The JetBrains Mono Project Authors | JetBrains Mono（文档站主题自托管字体） | SIL Open Font License 1.1（见 `docs-site/.vitepress/theme/fonts/LICENSE-jetbrains-mono.txt`） | 否 | 随 `docs-site` 静态文档站代码块渲染使用 |
| `docs-site/.vitepress/theme/vendor/animejs/` | Julian Garnier | Anime.js 4.5.0（文档站主题脚本） | MIT License（见 `docs-site/.vitepress/theme/vendor/animejs/LICENSE.md`） | 否 | 随 `docs-site` 静态文档站前端交互动效分发 |

## 再分发与下游替换指引

1. **第三方开源字体与静态前端组件**：下游在再分发构建产物或站点时，须在分发产物或交互界面的合理法律声明位置保留 SIL OFL 1.1 / MIT / Apache-2.0 等原许可文件与版权声明。
2. **项目标识与默认 Logo**：在合法复制、构建、安装、运行或传递 AstrBot Resource Monitor 及其修改版本时，允许按 `ADDITIONAL_TERMS.zh-CN.md` 第八条正常保留或适配显示，亦可在下游修改版本中改名或替换为自有合法图标；不得以项目标识冒充官方发布或官方认证。

