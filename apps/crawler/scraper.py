import re
import logging
import apps.crawler.patch_langchain  # noqa: F401
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from scrapegraphai.graphs import SmartScraperGraph
from shared.config import config

class JobDetailSchema(BaseModel):
    title: str = Field(description="The official job title or position name. Example: 'Senior Software Engineer'.")
    department: Optional[str] = Field(default=None, description="The department, group, or division offering this role (if mentioned, otherwise null).")
    location: str = Field(description="The city, state, or office location (if remote/hybrid, specify that).")
    salary: Optional[str] = Field(default=None, description="The salary range or payment structure (if mentioned, otherwise null).")
    description: str = Field(description="A comprehensive Markdown text compiling both the job responsibilities and minimum/preferred requirements.")


logger = logging.getLogger(__name__)

class ScrapeGraphScraper:
    """Intelligent extractor based on ScrapegraphAI"""

    def __init__(self):
        self.api_key = config.llm_api_key
        self.provider = config.llm_provider.lower()
        self.model = config.llm_model

    def _extract_urls_from_value(self, val: Any) -> List[str]:
        """Extract a list of URLs from any possible value, and clean up invalid punctuation tails at the end caused by Markdown or JSON wrappers"""
        if not val:
            return []
        if isinstance(val, list):
            res = []
            for item in val:
                res.extend(self._extract_urls_from_value(item))
            return res

        def clean_url(u: str) -> str:
            u = u.strip()
            # Loop to strip invalid Markdown, JSON, or punctuation tails from the end of the URL
            while u and u[-1] in ["]", "[", ")", "(", ",", ";", ".", ">", "<", "*", "!", '"', "'", "\\"]:
                u = u[:-1]
            return u

        if isinstance(val, str):
            # 1. Attempt to match Markdown link format [Text](URL)
            markdown_urls = re.findall(r'\[.*?\]\((.*?)\)', val)
            if markdown_urls:
                return [clean_url(u) for u in markdown_urls if clean_url(u)]

            # 2. Attempt to extract regular href or URL links
            urls = re.findall(r'(https?://[^\s\'"]+|/[^\s\'"]+)', val)
            if urls:
                return [clean_url(u) for u in urls if clean_url(u)]

            # 3. Simple comma/space separated extraction
            parts = [p.strip() for p in re.split(r'[\s,\n]+', val) if p.strip()]
            return [clean_url(p) for p in parts if (p.startswith("http") or p.startswith("/")) and clean_url(p)]

        return []

    def _is_llm_configured(self) -> bool:
        """Check if LLM configuration is available: has API Key, is local Ollama, or has Base URL"""
        if self.provider == "ollama" or config.llm_base_url:
            return True
        return bool(self.api_key)

    def _get_graph_config(self) -> Dict[str, Any]:
        model_str = f"{self.provider}/{self.model}"
        llm_config = {
            "model": model_str,
        }

        # Only write when not empty to avoid overwriting keyless configurations for certain local LLMs
        if self.api_key:
            llm_config["api_key"] = self.api_key

        # If local LLM endpoint is configured (e.g. Ollama or LocalAI)
        if config.llm_base_url:
            llm_config["base_url"] = config.llm_base_url

        if self.provider == "gemini":
            llm_config["temperature"] = 0.0

        # If model_tokens is configured (e.g. limit or specify the maximum token count of local LLM)
        llm_config_yaml = config.data.get("llm", {})
        if "model_tokens" in llm_config_yaml:
            llm_config["model_tokens"] = int(llm_config_yaml["model_tokens"])

        graph_config = {
            "llm": llm_config,
            "loader": {
                "browser": "playwright",
                "headless": True,
                "wait_until": "networkidle",
            },
            "verbose": False
        }
        return graph_config

    def extract_job_urls(self, source_content: str, base_url: str = None, job_url_keywords: List[str] = None, job_url_pattern: str = None) -> List[str]:
        # 1. Attempt fast extraction using BeautifulSoup and high-confidence regex, bypassing slow local LLMs
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
            
            soup = BeautifulSoup(source_content, "html.parser")
            
            # Automatically handle <base href="..."> tags in HTML to correct relative path concatenation baselines
            if base_url:
                base_tag = soup.find("base")
                if base_tag and base_tag.get("href"):
                    old_base = base_url
                    base_url = urljoin(base_url, base_tag.get("href").strip())
                    logger.info(f"Detected <base> tag. Updated base_url from '{old_base}' to '{base_url}'")
                    
            fast_urls = []
            
            # Compile custom URL pattern into regex
            compiled_pattern = None
            if job_url_pattern:
                try:
                    placeholder_regex = r"\{[^}]+\}"
                    temp_pattern = re.sub(placeholder_regex, "___WILDCARD_PLACEHOLDER___", job_url_pattern)
                    escaped_pattern = re.escape(temp_pattern)
                    pattern_str = escaped_pattern.replace("___WILDCARD_PLACEHOLDER___", r"[^/\s?#]+")
                    if pattern_str.startswith(r"\/"):
                        pattern_str = r".*" + pattern_str
                    if pattern_str.endswith(r"\/"):
                        pattern_str = pattern_str + r"?"
                    else:
                        pattern_str = pattern_str + r"\/?(?:\?.*)?$"
                    compiled_pattern = re.compile(pattern_str, re.IGNORECASE)
                except Exception as compile_err:
                    logger.warning(f"Failed to compile job_url_pattern '{job_url_pattern}': {str(compile_err)}")
            
            # Merge default and database-configured keywords
            match_keywords = ["/job/", "/jobs/", "/position/", "/detail/", "/details/"]
            if job_url_keywords:
                custom_kw = [str(k).lower().strip() for k in job_url_keywords if k]
                for ck in custom_kw:
                    if ck and ck not in match_keywords:
                        match_keywords.append(ck)
            
            for a in soup.find_all("a"):
                href = a.get("href")
                if not href:
                    continue
                href = href.strip()
                if not href or href.startswith("#") or href.startswith("javascript:"):
                    continue
                    
                href_lower = href.lower()
                is_job_link = False
                
                # Prioritize matching precise regex patterns
                if compiled_pattern:
                    full_href = urljoin(base_url, href) if base_url else href
                    if compiled_pattern.match(href) or compiled_pattern.match(full_href):
                        is_job_link = True
                
                # Fallback match common or custom high-confidence job details page paths (only active when no precise regex pattern is provided)
                if not compiled_pattern and any(p in href_lower for p in match_keywords):
                    is_job_link = True
                elif base_url and urljoin(base_url, href).lower() == href_lower:
                    # Avoid including the homepage, etc.
                    pass
                    
                if is_job_link:
                    full_url = urljoin(base_url, href) if base_url else href
                    fast_urls.append(full_url)
                    
            unique_fast = list(dict.fromkeys(fast_urls))
            
            # If custom keywords or matching patterns are provided, as long as at least one link matching that characteristic is found, trust and return it directly, 100% bypassing the LLM!
            min_required = 1 if (job_url_keywords or job_url_pattern) else 3
            if len(unique_fast) >= min_required:
                logger.info(f"Fast Heuristic Extractor: Successfully extracted {len(unique_fast)} job URLs (min_required={min_required}). Bypassing LLM.")
                return unique_fast
        except Exception as fast_err:
            logger.warning(f"Fast Heuristic Extractor failed: {str(fast_err)}. Falling back to LLM.")

        if not self._is_llm_configured():
            logger.warning("LLM configuration is incomplete (API Key and Base URL are both missing)!")
            return []

        prompt = (
            "Identify and extract all individual job detail URLs or links to specific positions listed in the provided HTML.\n"
            "Return them as a clean list of URLs. Make sure you extract the URLs EXACTLY as they appear in the HTML href attributes.\n"
            "DO NOT alter, simplify, or shorten the URLs. Keep all ID parameters, language-region codes, and path segments exactly as they are in the source HTML href (for example, if a link is '/en-sg/details/200596262-3278/site-reliability-engineer', you MUST return it exactly like that, do not change it to '/job/12345/job-title')."
        )
        graph_config = self._get_graph_config()

        logger.info("Initializing SmartScraperGraph for URL extraction...")
        smart_graph = SmartScraperGraph(
            prompt=prompt,
            source=source_content,
            config=graph_config
        )

        try:
            result = smart_graph.run()
            logger.info(f"SmartScraperGraph raw result for URLs: {result}")

            urls = []
            if isinstance(result, list):
                for item in result:
                    urls.extend(self._extract_urls_from_value(item))
            elif isinstance(result, dict):
                # Prioritize extraction based on common keys
                for key in ["job_urls", "urls", "links", "job_links", "content"]:
                    if key in result:
                        urls.extend(self._extract_urls_from_value(result[key]))

                # If not found under common keys, traverse all values as a fallback
                if not urls:
                    for val in result.values():
                        urls.extend(self._extract_urls_from_value(val))
            elif isinstance(result, str):
                urls.extend(self._extract_urls_from_value(result))

            # Deduplicate and filter empty values
            unique_urls = list(dict.fromkeys([u.strip() for u in urls if u and isinstance(u, str)]))
            logger.info(f"Filtered and parsed {len(unique_urls)} unique URLs from LLM result.")
            
            # --- URL Recovery (Physical URL Correction Mechanism) ---
            if base_url:
                logger.info("Starting post-processing URL recovery to match against actual HTML hrefs...")
                from bs4 import BeautifulSoup
                from urllib.parse import urlparse, urljoin
                
                soup = BeautifulSoup(source_content, "html.parser")
                
                # Automatically handle <base href="..."> tags in HTML to correct relative path concatenation baselines
                base_tag = soup.find("base")
                if base_tag and base_tag.get("href"):
                    base_url = urljoin(base_url, base_tag.get("href").strip())
                    
                real_hrefs = []
                for a in soup.find_all("a"):
                    href = a.get("href")
                    if href:
                        href = href.strip()
                        if href and not href.startswith("#") and not href.startswith("javascript:"):
                            abs_url = urljoin(base_url, href)
                            real_hrefs.append(abs_url)
                            
                recovered_urls = []
                for ext_url in unique_urls:
                    abs_ext_url = urljoin(base_url, ext_url)
                    if abs_ext_url in real_hrefs:
                        recovered_urls.append(abs_ext_url)
                        continue
                        
                    parsed = urlparse(abs_ext_url)
                    path = parsed.path.strip("/")
                    if not path:
                        recovered_urls.append(abs_ext_url)
                        continue
                        
                    segments = [s for s in path.split("/") if s]
                    if not segments:
                        recovered_urls.append(abs_ext_url)
                        continue
                        
                    target_segment = segments[-1]
                    
                    matched_href = None
                    for real_href in real_hrefs:
                        parsed_real = urlparse(real_href)
                        real_path_lower = parsed_real.path.lower()
                        
                        if target_segment.lower() in real_path_lower:
                            if "/job/" in real_path_lower:
                                matched_href = real_href
                                break
                            matched_href = real_href
                            
                    if matched_href:
                        logger.info(f"URL Recovery: Fixed malformed LLM URL '{abs_ext_url}' -> '{matched_href}'")
                        recovered_urls.append(matched_href)
                    else:
                        recovered_urls.append(abs_ext_url)
                        
                unique_urls = list(dict.fromkeys(recovered_urls))
                logger.info(f"Post-processing complete. Final unique URLs count: {len(unique_urls)}")
                
            return unique_urls
        except Exception as e:
            logger.error(f"Error extracting job URLs: {str(e)}")
            return []

    def _html_to_markdown(self, html_content: str) -> str:
        """Convert cleaned HTML to well-structured Markdown, handling spaces and newlines to prevent word sticking"""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return html_content
            
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Ensure extra tags are stripped
        for tag in soup(["script", "style", "svg", "path", "iframe", "head", "noscript", "link", "meta"]):
            tag.decompose()
            
        markdown_lines = []
        
        def process_node(node):
            if not node:
                return
            if isinstance(node, str):
                val = str(node)
                if val.strip() == "":
                    # As long as there is a space, non-breaking space, or newline, keep a single regular space to prevent inline elements from sticking together
                    if " " in val or "\xa0" in val or "\n" in val:
                        markdown_lines.append(" ")
                else:
                    # Keep leading and trailing spaces of the original text
                    leading = " " if val.startswith(" ") or val.startswith("\xa0") or val.startswith("\n") else ""
                    trailing = " " if val.endswith(" ") or val.endswith("\xa0") or val.endswith("\n") else ""
                    markdown_lines.append(leading + val.strip() + trailing)
                return
                
            if node.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                level = int(node.name[1])
                text = node.get_text(strip=True)
                if text:
                    markdown_lines.append(f"\n\n{'#' * level} {text}\n\n")
            elif node.name == "p":
                markdown_lines.append("\n")
                for child in node.children:
                    process_node(child)
                markdown_lines.append("\n")
            elif node.name == "li":
                markdown_lines.append("- ")
                for child in node.children:
                    process_node(child)
                markdown_lines.append("\n")
            elif node.name in ["ul", "ol"]:
                for child in node.children:
                    if child.name == "li":
                        process_node(child)
            else:
                if hasattr(node, "children"):
                    for child in node.children:
                        process_node(child)
                        
        body = soup.find("body") or soup
        process_node(body)
        
        # Combine text and clean up newlines
        markdown = "".join(markdown_lines)
        # Replace multiple consecutive spaces or non-breaking spaces with a single space
        markdown = re.sub(r'[ \t\u00a0\xa0]+', ' ', markdown)
        # Replace multiple consecutive newlines
        markdown = re.sub(r'\n{3,}', '\n\n', markdown)
        return markdown.strip()

    def _extract_description_from_json_ld(self, html_content: str) -> str:
        """Attempt to extract clean job description HTML from Schema.org JSON-LD structured data and convert to Markdown"""
        try:
            from bs4 import BeautifulSoup
            import json
        except ImportError:
            return ""
            
        soup = BeautifulSoup(html_content, "html.parser")
        for script_tag in soup.find_all("script", type="application/ld+json"):
            try:
                content = script_tag.get_text().strip()
                if not content:
                    continue
                data = json.loads(content)
                
                # Handle JSON-LD list
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            desc_html = item.get("description")
                            if desc_html:
                                return self._html_to_markdown(desc_html)
                elif isinstance(data, dict):
                    # Handle single object or Graph
                    if data.get("@type") == "JobPosting":
                        desc_html = data.get("description")
                        if desc_html:
                            return self._html_to_markdown(desc_html)
                    elif "@graph" in data:
                        for item in data["@graph"]:
                            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                                desc_html = item.get("description")
                                if desc_html:
                                    return self._html_to_markdown(desc_html)
            except Exception as e:
                logger.debug(f"JSON-LD parse error: {str(e)}")
        return ""

    def _clean_detail_html(self, html_content: str) -> str:
        """Strip highly redundant style, script, and media tags from HTML details pages, reducing LLM token burden by over 80%"""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return html_content
        
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "svg", "path", "iframe", "head", "noscript", "link", "meta"]):
            tag.decompose()
            
        body = soup.find("body")
        if body:
            return str(body)
        return str(soup)

    def extract_job_details(self, source_content: str, job_url: str) -> Dict[str, Any]:
        if not self._is_llm_configured():
            logger.warning("LLM configuration is incomplete (API Key and Base URL are both missing)! Returning default empty structure.")
            return {}

        prompt = "Extract structural details of the job post from the HTML."

        graph_config = self._get_graph_config()
        cleaned_source = self._clean_detail_html(source_content)
        logger.info(f"HTML cleaned for extraction: reduced from {len(source_content)} to {len(cleaned_source)} chars.")

        logger.info(f"Initializing SmartScraperGraph for job details on {job_url}...")
        smart_graph = SmartScraperGraph(
            prompt=prompt,
            source=cleaned_source,
            config=graph_config,
            schema=JobDetailSchema
        )


        try:
            result = smart_graph.run()
            logger.info(f"Successfully extracted job details for {job_url}")

            # Automatically strip single outer wrapper keys from LLM response (e.g. {"content": {...}})
            if isinstance(result, dict) and len(result) == 1:
                outer_key = list(result.keys())[0]
                if outer_key in ["content", "json", "data", "job"] and isinstance(result[outer_key], dict):
                    logger.info(f"Automatically unpacked outer key '{outer_key}' from LLM response.")
                    result = result[outer_key]

            import json
            def clean_str(val) -> str:
                if val is None:
                    return ""
                if isinstance(val, dict):
                    for k in ["description", "text", "content", "title", "name", "value"]:
                        if k in val and isinstance(val[k], (str, int, float)):
                            return str(val[k])
                    return json.dumps(val, ensure_ascii=False)
                return str(val)

            title_val = result.get("title") or result.get("position")
            dept_val = result.get("department")
            loc_val = result.get("location")
            salary_val = result.get("salary")
            desc_val = result.get("description") or result.get("content")

            # Prioritize extracting description Markdown from noise-free JSON-LD data as a complete fallback
            ld_desc = self._extract_description_from_json_ld(source_content)
            if ld_desc:
                full_markdown = ld_desc
            else:
                full_markdown = self._html_to_markdown(cleaned_source)

            final_desc = clean_str(desc_val)
            # Adaptive loss prevention verification: if the LLM-generated description is short (less than 1000 chars),
            # and the physically extracted full markdown is significantly longer (by over 300 chars),
            # automatically upgrade to the full markdown description to prevent truncation of Responsibilities and Requirements.
            if len(final_desc) < 1000 and len(full_markdown) > len(final_desc) + 300:
                logger.info(f"LLM extracted description is short ({len(final_desc)} chars). Auto-upgraded to complete markdown ({len(full_markdown)} chars) to prevent information loss.")
                final_desc = full_markdown
            elif not final_desc:
                final_desc = full_markdown

            details = {
                "title": clean_str(title_val) if title_val else "Unknown Position",
                "department": clean_str(dept_val) if dept_val else None,
                "location": clean_str(loc_val) if loc_val else "Unknown Location",
                "salary": clean_str(salary_val) if salary_val else None,
                "description": final_desc,
                "raw_metadata": result
            }
            return details
        except Exception as e:
            logger.error(f"Error extracting job details for {job_url}: {str(e)}")
            return {}

    def _extract_interactive_elements(self, html_content: str) -> str:
        """
        Simplify HTML, extracting only interaction elements related to pagination and Cookies, greatly reducing the LLM's token usage.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.warning("BeautifulSoup4 is not installed. Returning original html (not recommended).")
            return html_content

        soup = BeautifulSoup(html_content, "html.parser")
        interesting_tags = ["a", "button", "input", "select", "nav"]
        simplified_elements = []

        for tag in soup.find_all(interesting_tags):
            href = tag.get("href")
            cls = tag.get("class")
            id_attr = tag.get("id")
            text = tag.get_text(strip=True)

            cls_str = " ".join(cls) if isinstance(cls, list) else str(cls or "")
            id_str = str(id_attr or "")
            href_str = str(href or "")

            combined_text = (text + " " + cls_str + " " + id_str + " " + href_str).lower()
            keywords = ["page", "pagination", "next", "prev", "load-more", "cookie", "consent", "accept", "allow", "agree"]

            is_numeric_page = text.isdigit() and len(text) < 4
            has_keywords = any(kw in combined_text for kw in keywords)

            if has_keywords or is_numeric_page or tag.name in ["select", "nav"]:
                attrs = []
                if id_attr:
                    attrs.append(f'id="{id_attr}"')
                if cls:
                    attrs.append(f'class="{" ".join(cls) if isinstance(cls, list) else cls}"')
                if href:
                    attrs.append(f'href="{href}"')
                if tag.get("onclick"):
                    attrs.append(f'onclick="{tag.get("onclick")}"')
                if tag.get("aria-current"):
                    attrs.append(f'aria-current="{tag.get("aria-current")}"')
                if tag.get("aria-label"):
                    attrs.append(f'aria-label="{tag.get("aria-label")}"')

                attrs_str = " ".join(attrs)
                simplified_elements.append(f"<{tag.name} {attrs_str}>{text}</{tag.name}>")

        return "\n".join(simplified_elements)

    def _extract_fallback_next_selector(self, soup) -> str:
        """Heuristically search for possible next page button CSS selector"""
        candidates = []
        for tag in soup.find_all(["a", "button"]):
            onclick = tag.get("onclick") or ""
            cls = " ".join(tag.get("class") or [])
            aria_label = tag.get("aria-label") or ""
            text = tag.get_text(strip=True).lower()
            
            is_next = False
            if any(w in cls.lower() for w in ["go-to-next", "next-page", "next-btn", "btn-next", "pager-next"]):
                is_next = True
            elif "next" in aria_label.lower() and not any(w in aria_label.lower() for w in ["prev", "last", "first"]):
                is_next = True
            elif any(w in onclick.lower() for w in ["next_page", "nextpage", "goto_page", "gotopage"]):
                if "next_page" in onclick.lower() or "nextpage" in onclick.lower() or "goto_page(" in onclick.lower():
                    is_next = True
            elif text in ["next", "next page", "next >", "»"]:
                is_next = True
                
            if is_next:
                candidates.append(tag)
                
        if candidates:
            best_candidate = candidates[0]
            for c in candidates:
                cls = " ".join(c.get("class") or [])
                if "go-to-next" in cls.lower() or "next-page" in cls.lower():
                    best_candidate = c
                    break
                    
            tag_name = best_candidate.name
            id_attr = best_candidate.get("id")
            if id_attr:
                return f"{tag_name}#{id_attr}"
                
            cls_list = best_candidate.get("class") or []
            features = ["go-to-next", "next-page", "next", "next-btn", "btn-next", "pager-next"]
            feature_classes = [c for c in cls_list if any(f in c.lower() for f in features)]
            
            if feature_classes:
                return f"{tag_name}.{'.'.join(feature_classes)}"
                
            clean_classes = [c for c in cls_list if c not in ["inactive", "disabled", "active"]]
            if clean_classes:
                return f"{tag_name}.{'.'.join(clean_classes)}"
                
            aria_label = best_candidate.get("aria-label")
            if aria_label:
                return f'{tag_name}[aria-label="{aria_label}"]'
                
            return tag_name
        return None

    def _extract_fallback_cookie_selector(self, soup) -> str:
        """Heuristically search for possible Cookie acceptance button CSS selector"""
        for tag in soup.find_all(["button", "a", "div"]):
            id_attr = tag.get("id") or ""
            cls = " ".join(tag.get("class") or [])
            text = tag.get_text(strip=True).lower()
            
            if any(w in id_attr.lower() for w in ["accept-recommended-btn", "onetrust-accept-btn", "cookie-accept-btn", "accept-all-btn"]):
                return f"#{id_attr}"
            if "accept" in id_attr.lower() and "cookie" in id_attr.lower():
                return f"#{id_attr}"
            if any(w in cls.lower() for w in ["cookie-accept", "accept-cookie", "accept-all"]):
                if id_attr:
                    return f"#{id_attr}"
                return f"{tag.name}.{'.'.join(tag.get('class'))}"
            if text in ["allow all", "accept all", "agree", "accept", "allow recommended", "accept recommended"]:
                if id_attr:
                    return f"#{id_attr}"
                if cls:
                    clean_cls = [c for c in tag.get("class") or [] if c not in ["inactive", "disabled"]]
                    if clean_cls:
                        return f"{tag.name}.{'.'.join(clean_cls)}"
                return tag.name
        return None

    def detect_pagination_and_cookie(self, html_content: str, url: str) -> Dict[str, Any]:
        """
        Dynamically sniff pagination patterns and Cookie pop-up selectors based on LLM.
        """
        if not self._is_llm_configured():
            logger.warning("LLM configuration is incomplete! Skipping pagination sniffing.")
            return {
                "is_paginated": False,
                "pagination_type": "none",
                "url_template": None,
                "next_page_selector": None,
                "cookie_accept_selector": None
            }

        logger.info(f"Extracting interactive elements to sniff pagination and cookie configurations for {url}...")
        simplified_html = self._extract_interactive_elements(html_content)
        logger.info(f"HTML elements simplified. Size reduced from {len(html_content)} to {len(simplified_html)} chars.")

        prompt = (
            "Analyze the simplified HTML elements from a career list page and detect the following configurations:\n"
            f"Current Page URL: {url}\n\n"
            "Return a structured JSON with key details:\n"
            "1. is_paginated (boolean): Whether the page contains job list pagination/page numbers/next page buttons.\n"
            "2. pagination_type (string): One of 'url_template', 'next_button', 'load_more', 'scroll', 'none'.\n"
            "3. url_template (string/null): Only specify this if the page actually uses URL parameters for paging (i.e., you can see actual URLs like '.../jobs?page=2' or '/careers?p=3' in the href attributes of page numbers). If the page numbers or next buttons have href='#' or 'javascript:void(0)' or use onclick JS functions, the pagination_type MUST be 'next_button' and url_template MUST be null. DO NOT hallucinate or guess any template URL.\n"
            "4. next_page_selector (string/null): CSS selector for clicking the 'Next' page button (e.g. 'a.go-to-next' or '#next-btn'), else null. Ensure the selector is highly specific and MUST exist in the provided HTML (i.e., you can find the corresponding tag, class names, or attributes in the text. DO NOT hallucinate or guess any class or ID not present in the HTML).\n"
            "5. cookie_accept_selector (string/null): CSS selector for clicking the 'Allow All' / 'Accept' button in the Cookie Consent dialog/banner if exists. Ensure it MUST exist in the provided HTML.\n\n"
            "Strictly return the JSON structure without outer wrappers. Keep CSS selectors precise and existing in the text."
        )

        graph_config = self._get_graph_config()
        logger.info("Initializing SmartScraperGraph for pagination & cookie sniffing...")
        smart_graph = SmartScraperGraph(
            prompt=prompt,
            source=simplified_html,
            config=graph_config
        )

        try:
            result = smart_graph.run()
            logger.info(f"Sniffer raw result: {result}")

            if isinstance(result, dict) and len(result) == 1:
                outer_key = list(result.keys())[0]
                if outer_key in ["content", "json", "data", "config", "result"] and isinstance(result[outer_key], dict):
                    result = result[outer_key]

            def clean_sel(sel):
                if not sel:
                    return None
                sel = str(sel).strip()
                if sel.lower() in ["null", "none", ""]:
                    return None
                return sel

            raw_next_page_selector = clean_sel(result.get("next_page_selector"))
            raw_cookie_accept_selector = clean_sel(result.get("cookie_accept_selector"))
            url_template = clean_sel(result.get("url_template"))

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, "html.parser")

            # 1. Physically validate next_page_selector
            next_page_selector = None
            if raw_next_page_selector:
                try:
                    elements = soup.select(raw_next_page_selector)
                    if elements:
                        first_el = elements[0]
                        el_text = first_el.get_text(strip=True)
                        el_id = first_el.get("id") or ""
                        el_aria = first_el.get("aria-label") or ""
                        
                        is_digit = el_text.isdigit()
                        is_numeric_aria = "page" in el_aria.lower() and any(c.isdigit() for c in el_aria) and "next" not in el_aria.lower()
                        
                        if is_digit or is_numeric_aria:
                            logger.warning(f"LLM next_page_selector '{raw_next_page_selector}' matched a numeric page button instead of 'Next' button. Rejecting.")
                        else:
                            logger.info(f"LLM next_page_selector '{raw_next_page_selector}' verified SUCCESS.")
                            next_page_selector = raw_next_page_selector
                    else:
                        logger.warning(f"LLM next_page_selector '{raw_next_page_selector}' verified FAILED (no match).")
                except Exception as e:
                    logger.warning(f"LLM next_page_selector '{raw_next_page_selector}' verified FAILED (syntax error): {str(e)}")

            # 2. If next_page_selector is empty or validation fails, trigger heuristic extraction
            if not next_page_selector:
                fallback_next = self._extract_fallback_next_selector(soup)
                if fallback_next:
                    logger.info(f"Fallback next_page_selector auto-extracted: '{fallback_next}'")
                    next_page_selector = fallback_next

            # 3. Physically validate cookie_accept_selector
            cookie_accept_selector = None
            if raw_cookie_accept_selector:
                try:
                    elements = soup.select(raw_cookie_accept_selector)
                    if elements:
                        logger.info(f"LLM cookie_accept_selector '{raw_cookie_accept_selector}' verified SUCCESS.")
                        cookie_accept_selector = raw_cookie_accept_selector
                    else:
                        logger.warning(f"LLM cookie_accept_selector '{raw_cookie_accept_selector}' verified FAILED (no match).")
                except Exception as e:
                    logger.warning(f"LLM cookie_accept_selector '{raw_cookie_accept_selector}' verified FAILED (syntax error): {str(e)}")

            # 4. If cookie_accept_selector is empty or validation fails, trigger heuristic extraction
            if not cookie_accept_selector:
                fallback_cookie = self._extract_fallback_cookie_selector(soup)
                if fallback_cookie:
                    logger.info(f"Fallback cookie_accept_selector auto-extracted: '{fallback_cookie}'")
                    cookie_accept_selector = fallback_cookie

            # 5. Physically validate the authenticity of url_template
            if url_template:
                import urllib.parse
                has_match = False
                try:
                    # Replace {page} with regex \d+ match
                    parsed_template = urllib.parse.urlparse(url_template)
                    template_path_query = parsed_template.path
                    if parsed_template.query:
                        template_path_query += "?" + parsed_template.query
                    
                    pattern_str = re.escape(template_path_query).replace(r'\{page\}', r'\d+')
                    if not pattern_str.startswith('/'):
                        pattern_str = r'.*' + pattern_str
                        
                    rx = re.compile(pattern_str)
                    for a_tag in soup.find_all("a"):
                        a_href = a_tag.get("href")
                        if a_href and rx.search(a_href):
                            has_match = True
                            break
                except Exception as e:
                    logger.warning(f"URL template '{url_template}' compile failed: {str(e)}")

                if not has_match:
                    logger.warning(f"LLM url_template '{url_template}' verified FAILED: No href matches pattern.")
                    url_template = None
                else:
                    logger.info(f"LLM url_template '{url_template}' verified SUCCESS.")

            # 6. State reset and adaptive correction
            is_paginated = bool(result.get("is_paginated", False)) or bool(next_page_selector) or bool(url_template)
            pag_type = str(result.get("pagination_type") or "none").lower()

            if next_page_selector and not url_template:
                pag_type = "next_button"
            elif url_template and not next_page_selector:
                pag_type = "url_template"
            elif not next_page_selector and not url_template:
                is_paginated = False
                pag_type = "none"

            return {
                "success": True,
                "is_paginated": is_paginated,
                "pagination_type": pag_type,
                "url_template": url_template,
                "next_page_selector": next_page_selector,
                "cookie_accept_selector": cookie_accept_selector
            }
        except Exception as e:
            logger.error(f"Error sniffing pagination & cookie configurations: {str(e)}")
            return {
                "success": False,
                "is_paginated": False,
                "pagination_type": "none",
                "url_template": None,
                "next_page_selector": None,
                "cookie_accept_selector": None
            }

scraper = ScrapeGraphScraper()


