import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MarkdownBody } from "./MarkdownBody";

function html(text: string): string {
  return renderToStaticMarkup(<MarkdownBody text={text} />);
}

describe("MarkdownBody (GFM correctness — the old hand parser faked or dropped all of these)", () => {
  it("preserves real heading hierarchy instead of flattening to h3/h4", () => {
    const out = html("# 标题一\n\n## 标题二\n\n### 标题三");
    expect(out).toContain("<h1>标题一</h1>");
    expect(out).toContain("<h2>标题二</h2>");
    expect(out).toContain("<h3>标题三</h3>");
  });

  it("renders real nested lists, not <p> rows faking bullets", () => {
    const out = html("1. 第一步\n2. 第二步\n   - 子项\n");
    expect(out).toContain("<ol>");
    expect(out).toContain("<ul>");
    expect((out.match(/<li>/g) ?? []).length).toBe(3);
    expect(out).not.toContain("finalOrdered");
  });

  it("renders --- as a horizontal rule, not literal text", () => {
    const out = html("上文\n\n---\n\n下文");
    expect(out).toContain("<hr/>");
    expect(out).not.toContain("---");
  });

  it("renders > blockquotes and *emphasis*", () => {
    const out = html("> **优化手段**：随机选择基准\n\n用 *斜体* 强调");
    expect(out).toContain("<blockquote>");
    expect(out).toContain("<em>斜体</em>");
    expect(out).not.toContain("&gt; ");
  });

  it("keeps pipe tables inside the horizontal-scroll wrapper", () => {
    const out = html("| A | B |\n| --- | --- |\n| 1 | 2 |");
    expect(out).toContain("markdownTableWrap");
    expect(out).toContain("markdownTable");
    expect(out).toContain("<th>A</th>");
    expect(out).toContain("<td>1</td>");
  });

  it("keeps fenced code inside the copy-button wrapper", () => {
    const out = html("```python\nprint(1)\n```");
    expect(out).toContain("markdownCodeWrap");
    expect(out).toContain("markdownCode");
    expect(out).toContain("print(1)");
    expect(out).toContain("复制");
  });

  it("opens http links in a new tab and never emits javascript: targets", () => {
    const out = html("[官网](https://example.com) 与 [坏链](javascript:alert(1))");
    expect(out).toContain('href="https://example.com"');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
    expect(out).not.toContain("javascript:");
  });

  it("never renders raw HTML from model output", () => {
    const out = html('安全 <script>alert("x")</script> 文本');
    expect(out).not.toContain("<script>");
  });
});
