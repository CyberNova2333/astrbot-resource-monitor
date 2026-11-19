# 实施与填写指南 / Implementation and Completion Guide

**配套版本 / Companion version:** v1.6.7-r4

> **非规范性说明：** 本文件用于部署、填写和工程理解，不是附加许可证，也不增设、减免或改变许可条件。实际权利与义务以有效基础许可证、中文附加条款正文及相应独立授权为准。工程例示不是对具体作品关系或授权充分性的最终认定。中文、英文说明均应与正文共同阅读。
>
> **Non-normative notice:** This guide supports deployment, record completion, and engineering understanding. It is not an additional license and does not add, waive, or alter license conditions. Rights and obligations are determined by valid base licenses, the authoritative Chinese additional terms, and relevant independent permissions. Engineering examples are not final findings about work relationships or sufficient authorization. Read both language versions with the operative terms.

## 1. 部署、清单与记录范围 / Deployment, manifest, and record scope

在根目录保留实际采用的完整基础许可证，并按 AGPLv3 第 7 条在相关源文件指明适用附加条款或其查阅位置。根目录文件的存在不证明全仓库采用同一许可。填写项目名称、项目方、来源和版本占位项时，按具体材料核实权限；不要把待填写内容当成已核实事实。综合清单采用四分区：本项目人类作者与贡献者、AI Agent 与自动化辅助工具、上游基线／依赖／第三方代码、独立美术／字体／项目标识资产。该工程组织方案不要求下游采用同一文件名、字段或工作流，声明迁移依第 3.7 款。

Retain the complete base license actually used at the repository root, and identify applicable additional terms or their location in the relevant source files as required by AGPLv3 Section 7. Root files do not establish a single license for the entire repository. Verify authority for the relevant material when completing project, party, source, and version placeholders; placeholders are not verified facts. The unified manifest has four sections: Project Human Authors & Contributors; AI Agents & Automated Assistants; Upstream Baselines, Dependencies & Third-Party Code Components; and Independent Artwork, Fonts & Project Identifier Assets. This engineering arrangement does not require downstream users to adopt identical names, fields, or workflows; Section 3.7 governs migration of notices.

## 2. 实际引入方式与覆盖范围 / Actual incorporation and review coverage

在清单中区分 Fork、Cherry-pick、源码快照、内嵌库、直接或传递依赖、仅构建工具、运行时组件、随包二进制和外部服务调用。记录材料的实际路径、发行物位置、来源、所采用版本、原始许可文本和相关声明。未出现在 Git Author、Committer 或 Co-authored-by 中的快照作者仍可能拥有相关权利。清单中的几行记录不能证明完成全量依赖或发行物审计，应据实标明未核实范围。

Distinguish forks, cherry-picks, source snapshots, embedded libraries, direct or transitive dependencies, build-only tools, runtime components, bundled binaries, and external service calls. Record actual paths, distribution locations, sources, adopted versions, original license texts, and relevant notices. Rights in snapshot material may belong to persons absent from Git Author, Committer, or Co-authored-by fields. A few manifest entries do not establish a complete dependency or distribution audit; identify unverified scope accurately.

## 3. 声明迁移与字体资产 / Migrating notices and handling font assets

可在清单中索引历史 `AUTHORS`、`NOTICE`、`COPYING`、`LICENSE`、`LICENSE.TXT`、`THIRD_PARTY.md`、`THIRD_PARTY_NOTICES.md`、`UPSTREAM.md` 或 `LICENSES/`；迁移时按原许可保留实际要求的完整文本、声明与位置，不因采用统一清单而删除，也不机械抄写多份。Apache、MIT、BSD 等分别按实际文本处理，不统一假定都要求名为 `NOTICE` 的文件。OFL 字体按该字体包的实际许可、版权声明及已声明的保留字体名称（RFN）记录，不从品牌或其他字体推测。CC BY 等独立资产按其有效许可记录署名、修改及展示方式；这些说明不统一要求所有字体或视觉资产在每个界面显示署名。

The manifest may index legacy `AUTHORS`, `NOTICE`, `COPYING`, `LICENSE`, `LICENSE.TXT`, `THIRD_PARTY.md`, `THIRD_PARTY_NOTICES.md`, `UPSTREAM.md`, or `LICENSES/` files. When migrating, retain the full texts, notices, and locations actually required by each original license; a unified manifest does not authorize deletion or require mechanical duplication. Apply the actual Apache, MIT, BSD, or other license text rather than assuming every license requires a file named `NOTICE`. For OFL fonts, record the package's actual license, copyright notices, and declared Reserved Font Names (RFNs), without inferring them from branding or other fonts. For independent assets under CC BY or other licenses, record the applicable attribution, modification, and presentation arrangements. These notes do not require every font or visual asset to be attributed in every interface.

## 4. 源码渠道与版本 / Source channels and versions

把可选的上游仓库致谢与实际运行或传递版本的对应源码获取区分。上游链接只有在确实满足适用条款对版本、完整内容和提供方式的要求时，才可能成为有效的获取途径。对第 9.5 款所涵盖的扩展，可用可完整下载的版本归档或仓库落实第 9.5(b) 项：按版本标明实际起算日、持续通道和获取位置，不用只读片段或失效业务账号代替通道。至少九十日是该项附加许可的条件，不是一般 AGPL 期限，也不免除更长的实际义务。具体规则以第 9.5(b)、9.6 款为准。

采用 CI/CD 持续部署时，不宜仅提供每次发版即被覆盖、且无法取得所需历史版本源码的单一 `latest` 下载链接。可按实际传递或用于服务的扩展模块版本保留可完整下载的归档、版本链接或其他持续可用的获取方式，落实第 9.5(b) 项按各版本分别计算的保留期限。`latest` 别名可以继续提供，但不能使仍在该项所要求保留期限内的版本源码失去获取渠道；本提示不增加逐次提交归档义务，九十日要求仍仅在该项附加许可的实际适用范围内生效。

Distinguish optional upstream-repository credit from access to Corresponding Source for the version actually run or conveyed. An upstream link can form part of valid access only when it meets the applicable requirements concerning version, complete content, and delivery method. For extensions covered by Section 9.5, fully downloadable version archives or repositories can implement Section 9.5(b): track each version's actual starting point, continuing channel, and access location, rather than substituting read-only fragments or an expired business account. The ninety-day minimum is a condition of that additional permission, not a general AGPL period, and does not displace longer applicable obligations. Sections 9.5(b) and 9.6 govern.

For CI/CD and continuous deployment, avoid relying solely on a single `latest` download link that is overwritten with each release and leaves the required earlier versions' source unavailable. Fully downloadable archives, version-specific links, or other continuing access may be retained for the extension module versions actually conveyed or used to provide the service, implementing the retention periods calculated separately for each version under Section 9.5(b). A `latest` alias may remain available, but must not leave versions still within the retention period required by that condition without source access. This guidance adds no requirement to archive every commit; the ninety-day requirement continues to apply only within the actual scope of that additional-permission condition.

## 5. 人类分区与真实角色 / Human contributors and actual roles

可结合实际可取得的 Git 历史中的 `Author`、`Committer`、`Co-authored-by` 字段与可核实贡献及权利记录，填写 `ASSETS_LICENSES.md` 第一分区。合并者、提交者、审阅者、实际创作者、版权持有人和组织代表可以不同。组织、团队、联合推出关系以及合法使用的笔名宜据实说明；仅有工具账户名称时，可依据核实的记录补充真实人类或组织角色，而无需重写 Git 历史。

The first section of `ASSETS_LICENSES.md` may combine available Git `Author`, `Committer`, and `Co-authored-by` fields with verifiable contribution and rights records. Merger, submitter, reviewer, creator, copyright holder, and organizational representative may differ. Describe organizations, teams, co-launch relationships, and lawfully used pseudonyms accurately. Verified human or organizational roles may be added when Git records show only a tool account, without rewriting history.

## 6. 工具分区与授权证据 / Tool records and authorization evidence

第二分区可以记录 AI、自动化工具、技术账户及可核实的使用或提交上下文，供工程审计参考；不向工具本身要求版权许可同意。有效声明可以来自有权主体本人，也可以由具有可核实代表权限的工具传达；单独的机器人“同意”、自动勾选或提交记录不证明实际权利人同意。`meta.json`、合并请求和贡献声明是证据渠道，不是因文件存在就自动授权。纯工程记录可省略，但其中实际应保留的法律声明需要保留或合规迁移。

The second section may record AI and automation tools, technical accounts, and verifiable usage or submission context for engineering audits; copyright agreement is not requested from the tool itself. An authorized party may make a valid statement directly or through a tool with verifiable representative authority. A bot's agreement, automatic checkbox, or submission alone does not establish the actual rights holder's agreement. Metadata, merge requests, and contribution statements are evidence channels, not automatic grants. Purely engineering records may be omitted while their required legal notices remain preserved or compliantly migrated.

## 7. 历史贡献与意见状态 / Inherited contributions and recorded positions

经 Fork、拣选或历史继承带入、尚无可核实明确意见的贡献，可以按第 1.7(b) 项记录为“未发表意见”。这不表示曾经单独征询或对方拒绝，也不排除其他可核实的既有授权。一个人的标签不宜覆盖其所有历史、未来或共同作者材料；同一主体可按材料及版本分别记录。对应的英文标签同样是事实指引。

Contributions inherited through forks, cherry-picks, or history without a verifiable recorded express position may be marked under Section 1.7(b) as having no recorded position. This implies neither individual consultation nor refusal and does not exclude other verifiable existing authorization. A person's label should not stand for all historical, future, or co-authored material; statuses may differ by material and version. Equivalent English labels likewise indicate records of facts.

## 8. 可选来源追溯 / Optional provenance records

为便于检查具体版本，可保留项目名、上游 URL 及可点击或可复制的地址；多次合并或拣选时，可在发行说明或来源记录中列明分叉前最后一个上游提交和历次纳入材料的提交哈希。快照或归档可以记录原来源、可识别版本和本地修改边界。继续维护清单时，可同步实际材料、角色和已核实状态，保留超出强制范围的真实致谢。这些均属第 4.1—4.2 款建议，不要求披露与许可履行无关的个人信息或内部审计数据，也不替代实际版本的对应源码。

To aid version-level tracing, retain the Project name and upstream URL in clickable or copyable form. For repeated merges or cherry-picks, release notes or provenance records may identify the last upstream commit before the fork and commits subsequently incorporated. Snapshots or archives may record source, identifiable version, and local modification boundaries. Maintained manifests may track actual material, roles, verified statuses, and truthful acknowledgments beyond mandatory scope. These are recommendations under Sections 4.1–4.2, not requirements to disclose unrelated personal or internal audit data, and do not replace Corresponding Source for the actual version.

## 9. 身份陈述与技术兼容 / Identity statements and technical compatibility

在线托管、云端创作、运行平台等都可涉及第五条。对外包注册表、发行页、界面、签名证书、公钥或信任列表都可能向用户传递组件来源或认证含义，宜保证与真实制作、签发、维护和授权关系一致。程序内部为编译或插件接口兼容保留原包名、命名空间和导入路径，本身不表示官方发布。准确描述自身新增贡献与虚称上游核心为自研专有引擎应予区分；实际规则仍以第五条为准。

Hosted applications, cloud authoring, and execution platforms can fall within Article 5. Public registries, release pages, interfaces, signing certificates, public keys, and trust lists may communicate origin or certification, so their presentation should match actual creation, signing, maintenance, and authorization. Keeping internal package names, namespaces, and import paths for compilation or plugin compatibility does not by itself imply an official release. Accurate descriptions of one's own additions differ from presenting upstream core components as a self-developed proprietary engine; Article 5 remains controlling.

## 10. 配置、资源及译文判断示例 / Configuration, resources, and translations

本说明解释第 6.1—6.3 款，不另设修改定义或豁免。站点标题、域名、端口、语言、既有主题选项和运行参数仍须通过既有机制设置，且操作本身不构成修改。`config`、`assets` 或 `locales` 目录中的文件可能包含程序逻辑、模板、样式或其他受保护表达；模型提示词也不因出现在语言包中成为界面翻译。忠实翻译安全提示、商业条款，或采用同源同实质内容的文档语言版本，并不因此失去译文豁免。正常构建产生的哈希或环境差异不单独构成修改。

These examples explain Sections 6.1–6.3 without adding a definition or exemption. Site titles, domains, ports, languages, existing theme choices, and runtime parameters must still be set through existing mechanisms without the operation itself constituting a modification. Files in `config`, `assets`, or `locales` directories may contain program logic, templates, styles, or other protected expression; model prompts do not become interface translations merely by appearing in language packs. Faithful translations of safety notices or commercial terms, and documentation language versions from the same source with the same substance, are not excluded from the translation exemption on that ground. Normal build hash or environment differences do not alone establish modification.

## 11. 修改说明及可选来源记录 / Modification notices and optional provenance

第 6.4 款允许按作品形态选择法律信息界面、版本信息、发行说明或随附文档。准确用语可包括“修改版”“基于 AstrBot Resource Monitor 的派生版本”；符合第 6.2 款条件的译文修改可写“本地化译文修订”。日期须如实反映所提供版本的修改，不能仅列早期分叉日期掩盖后续修改。上游标签、提交哈希及完整合并、拣选或来源台账是追溯辅助，不替代对应源码，也不成为新必填项。

Section 6.4 permits legal-information interfaces, version information, release notes, or accompanying documentation according to the work. Accurate wording may include "Modified Version" or "Derivative version based on AstrBot Resource Monitor"; qualifying translation modifications may use "Localization Translation Revision." Dates must truthfully reflect modifications to the supplied version without hiding later changes behind an early fork date. Upstream tags, hashes, and complete merge, cherry-pick, or provenance logs aid traceability, but do not replace Corresponding Source or become new mandatory fields.

## 12. 服务入口及界面关系 / Service entry points and interface relationships

运行界面、内容创作者编辑器和其他交互界面应按第 6.5 款的实际功能与作品关系判断。源码入口须让相关用户合理发现，孤立但技术可访问的地址不足。另写前端、拆分进程或经网关不能仅凭架构名称决定声明义务；同一运营者也不自动使独立前端受 AGPL 约束。应分别核对网络源码义务、项目修改标识、实际适用的合理声明及独立作品自身许可，不能混为一个触发条件。

Runtime interfaces, content-creator editors, and other interfaces are assessed under Section 6.5 by actual function and work relationships. Relevant users must reasonably be able to discover source access; an isolated but technically accessible address is insufficient. Separately writing a frontend, splitting processes, or using a gateway does not let architectural labels decide notice obligations; a common operator does not automatically place an independent frontend under AGPL. Assess network source obligations, Project modification marking, actually applicable notices, and each independent work's license separately, without using a single combined trigger.

## 13. 清单记录项目与特殊授权 / Manifest fields and special permissions

落实第 7.7 款时，对列入清单的组件或资产记录：可识别名称与路径、原始作者或版权持有人、上游来源、有效许可证及版本或具体授权文本、许可文本位置、引入方式与适用边界。本地修改、GPL 版本选择和组合依据在引入方式及适用边界中区分，项目标识和特殊授权范围亦明确说明。具体表格继续由清单承载；本说明不要求下游照抄字段或运行自动化，也不把清单变成全依赖审计证明。授权效力仍由第一条决定。

To implement Section 7.7, record each listed component or asset's identifiable name and path, original author or copyright holder, upstream source, valid license and version or specific authorization text, license-text location, introduction method, and applicability boundaries. Distinguish local modifications, GPL version choices, and combination bases within the introduction and applicability descriptions, and identify Project Identifiers and special authorization scopes. The manifest continues to carry the actual tables. This guidance does not require downstream recipients to copy fields or run automation, or turn the manifest into certification of an exhaustive dependency audit. Article 1 still determines authorization effect.

## 14. 两个第十三条及多许可架构示例 / The two Section 13 provisions and multiple-license architectures

第 7.4 款引用 GPLv3 与 AGPLv3 各自的第 13 条：前者允许与 AGPLv3 作品组合并说明相关网络交互要求对组合的适用；后者规定远程网络交互义务并允许与 GPLv3 作品组合。组合仍保留各部分许可证，并按实际要求提供相应源码。GPL-2.0-only 内核驱动、补丁及其他组件不能仅因同仓库或清单登记套用该路径。分目录、分仓库、独立 AAR/JAR/归档、单独进程及“隔离”标注只是工程事实，应结合表达、修改、链接及运行时交互依第 7.5 款判断。

Section 7.4 references Section 13 of GPLv3 and Section 13 of AGPLv3. The former permits combinations with AGPLv3 works and describes application of related network-interaction requirements; the latter provides remote network interaction obligations and permits combinations with GPLv3 works. Each portion retains its license, with source supplied as actually required. GPL-2.0-only kernel drivers, patches, and other components cannot use this path merely through shared repositories or manifest entries. Separate directories, repositories, AAR/JAR/archive files, processes, and "isolated" labels are engineering facts; expression, modifications, linking, and runtime interaction must be assessed under Section 7.5.

## 15. 独立内容和程序输出 / Independent content and program output

第 9.4 款所称内容或扩展可包括内容作品、资源包、主题皮肤或松耦合扩展单元；名称不决定法律性质。应先核实是否包含适用材料的受保护表达或构成改编、衍生作品。程序输出是否被 AGPLv3 覆盖，直接参照 AGPLv3 第 2 条；使用某个编辑器本身并不使全部独立创作内容归项目方许可。

Content or extensions referred to in Section 9.4 may include creative content, resource packs, themes, or loosely coupled extension units; those labels do not determine legal status. First examine whether protected expression from Covered Material is incorporated or an adaptation or derivative work exists. AGPLv3 Section 2 directly governs whether program output is covered; using an editor does not by itself place all independently created content under the Project Parties' licensing authority.

## 16. 对应源代码定义的阅读提示 / Reading the Corresponding Source definition

第 9.5(b) 项直接采用 AGPLv3 第 1 条的完整定义和排除规则。核查时应关注修改首选形式、生成/安装/运行/修改所需文件及脚本、接口定义和该条适用的排除项，而不是只检查仓库中是否存在名为 `src` 的目录。正式条款中完整下载、无附加门槛、各版本至少 90 日的通道等要求继续独立适用；不要把这些定制条件误认为 MIT 等许可本身的要求。

Section 9.5(b) directly adopts the complete definition and exclusions in AGPLv3 Section 1. Review the preferred form for modification, the files and scripts needed to generate, install, run, and modify the work, interface definitions, and the exclusions actually applicable under that Section, rather than merely checking for a directory named `src`. The formal terms' separate conditions on full download, absence of extra barriers, and the channel maintained for at least ninety days per version continue to apply; those custom conditions should not be confused with requirements imposed by MIT or another selected license itself.

## 17. 附加许可条件不满足的两类情形 / Failure to meet additional-permission conditions

第 9.6 款区分自始不满足第 9.5(a)—(e) 项与后来才不再满足的组合或行为。前者例如缺少必要授权，或实际采用第 9.5(d) 项禁止的闭源紧密耦合伴生组件/远程中转；这些案例仍须按具体条款和事实判断。专利条件造成的主体资格终止另按第 9.5(f) 项判断，不能仅以某一模块不再合格代替其全组合范围规则，也不能将其与基础 AGPLv3 第 8 条的终止恢复机制混同。

Section 9.6 distinguishes combinations or acts that fail Sections 9.5(a)–(e) from the outset from those that cease to satisfy them later. The former may include missing necessary authorization or a closed-source tightly coupled companion or remote relay prohibited by Section 9.5(d); the actual terms and facts still control. Patent-related termination of a party's eligibility is assessed separately under Section 9.5(f). It must not be reduced to the loss of qualification of only one module, or confused with termination and reinstatement of base AGPLv3 rights under its Section 8.

## 原始许可证参考 / Original license references

- [GNU AGPLv3](https://www.gnu.org/licenses/agpl-3.0.en.html)
- [GNU GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)
- [GNU GPLv2](https://www.gnu.org/licenses/old-licenses/gpl-2.0-standalone.html)
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- [SIL Open Font License 1.1](https://openfontlicense.org/open-font-license-official-text/)
- [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/legalcode.en)

本节链接供查阅；不代替实际许可证要求随附的完整文本或声明。

These links are references and do not replace full texts or notices that must accompany material under its applicable license.
