from haystack import component
from haystack.dataclasses import ByteStream, Document
from haystack_integrations.components.generators.ollama import OllamaGenerator
from haystack.components.builders import PromptBuilder
from haystack.components.fetchers import LinkContentFetcher
from tqdm import tqdm
import pandas as pd
import json
from pathlib import Path
import os
import re
from jinja2 import Template, meta
from typing import Any

def construct_trustpilot_url(company_name: str, stars: int | None=None, page: int = 1) -> str:
    """Generates trustpilot.co.uk url for a company and specific star rating if specified.

    Args:
        company_name (str): URL of the homepage of the company you are interested in e.g. `www.118118money.com`
        stars (int | None, optional): Star rating to be filtered to. Defaults to None.
        page (int, optional): Review page to be retrieved. 40 reviews are returned per page. Defaults to 1.

    Returns:
        str: url for trustpilot.co.uk
    """
    res = f"https://uk.trustpilot.com/review/{company_name}?sort=recency"
    
    if page > 1:
        res += f"&page={page}"
    
    if stars is not None:
        res += f"&stars={stars}"
    return res

def get_prompt_template_by_name(prompt_template: str) -> str:
    base_path = Path(os.getcwd()) / "prompts"
    file_name = f"{prompt_template}.md"
    
    files = os.listdir(base_path)
    
    if file_name not in files:
        raise ValueError("Incorrect prompt template provided.")
    
    with open(base_path / file_name, "r") as f:
        return f.read()
    
def get_fabric_prompt(prompt_name: str) -> str:
    url = f"https://raw.githubusercontent.com/danielmiessler/fabric/main/patterns/{prompt_name}/system.md"
    fetcher = LinkContentFetcher()
    res = fetcher.run(urls=[url])
    return res["streams"][0].data.decode()

@component
class TrustPilotReviewExtractor:
    """Extracts reviews from TrustPilot url and returns them as a list of documents.
    The data returned in the document is essentially duplicated with the
    Document.content being an amalgamation of the information gathered.

    Returns:
        list[Document]: Reviews on the page mapped into a Document class.
    """
    def __init__(self, review_format: str="long"):
        if review_format not in ["short", "long", "author+content"]:
            raise ValueError("Review format is incorrect")
        self.review_format = review_format
    
    def convert_to_document(self, html_dict: dict[str, str], review_format: str="long") -> Document:
        from haystack.dataclasses import Document
        
        if review_format == "long":
            content=(f'{html_dict["author_id"]} aka {html_dict["author_name"]}\n'
                f'{html_dict["stars"]}\n'
                f'#{html_dict["headline"]}\n'
                f'{html_dict["content"]}')
        elif review_format == "author+content":
            content = f'{html_dict["author_name"]} wrote:\n{html_dict["content"]}'
        else:
            content = html_dict["content"]
        
        
        res = Document(content=content, meta=html_dict)
        return res
    
    def get_articles_from_stream(self, streams):
        from bs4 import BeautifulSoup
        
        res = []
        
        for s in streams:
            stream_res = []
            
            soup = BeautifulSoup(s.data.decode(), "html.parser")
            
            articles = soup.find_all("article")
            
            for a in articles:
                stars = a.find("div", class_=re.compile("star-rating")).find("img")["alt"]
                
                author = a.find("aside").find("div", class_=re.compile("consumerDetailsWrapper")).find("a", class_=re.compile("consumerDetails"))
                author_id = author["href"]
                author_name = author.find("span").get_text()
                
                headline = a.find("h2").get_text()
                
                paragraphs = [p.get_text() for p in a.find_all("p")]
                paragraphs = "\n".join(paragraphs)
                paragraphs = re.split("(Reply from)", paragraphs)
                reply = " ".join(paragraphs[1:])
                
                paragraphs = paragraphs[0].split("Date of experience: ")
                date_of_experience = paragraphs[1]
                paragraphs = paragraphs[0]
                
                content_as_dict = {
                    "author_id": author_id,
                    "author_name": author_name,
                    "stars": stars,
                    "headline": headline,
                    "content": paragraphs,
                    "reply": reply,
                    "date": date_of_experience
                }
                
                stream_res.append(self.convert_to_document(content_as_dict, self.review_format))
            res.append(stream_res)
                
        return res
    
    @component.output_types(documents=list[Document])
    def run(self, html:list[ByteStream]):
        return {"documents": self.get_articles_from_stream(html)}
    
@component
class BytestreamToStr:
    """Converts list of Bytestream s to plain strings.

    Returns:
        list[str]: Converted bytestreams.
    """    
    @component.output_types(strings=list[str])
    
    def run(self, streams: list[ByteStream]):
        return {"strings": [str(s.data) for s in streams]}
    
@component
class FlattenDocumentsList:
    """Flattens list of lists into a single list. Useful when yo have nested lists in the pipeline.

    Returns:
        list[Document]: flattened list.
    """    
    @component.output_types(documents=list[Document])
    
    def run(self, documents: list[Document]):
        while any(isinstance(i, list) for i in documents):
            documents = [x for xs in documents for x in xs]
        return {"documents": documents}
    
@component
class TopNDocuments:
    def __init__(self, n: int):
        self.n = n
        
    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]):
        return {"documents": documents[:self.n]}

@component
class ForEach_OllamaLLMTaskRunner:
    def __init__(
            self, 
            model_name: str,
            ollama_endpoint: str, 
            template: str, 
            include_meta: bool=False,
            generation_kwargs: dict[str, any] | None=None
        ):
        self.template = template
        self.include_meta = include_meta
        self.generator = OllamaGenerator(
                            model=model_name, 
                            url=f"{ollama_endpoint}/api/generate",
                            generation_kwargs=generation_kwargs
                        )
        
    @component.output_types(replies=list[str])
    def run(self, input_documents: list[Document]):
        prompts = [f"{self.template}\n{d.content}\n\nOUTPUT:" for d in input_documents]
        
        replies = []
        for p in tqdm(prompts):
            replies.append(self.generator.run(p))
        
        if not self.include_meta:
            res = [" ".join(r["replies"]) for r in replies]
        else:
            res = replies
        return {"replies": res}

@component
class ExtractReply:
    
    @component.output_types(replies=list[str])
    
    def run(self, replies: list[str]):
        res = [" ".join(r["replies"]) for r in replies]
        return {"replies": res}

@component
class JSONtoPandas:
    
    @component.output_types(df=pd.DataFrame)
    
    def run(self, jsons: list[str]):
        jsons = [json.loads(j) for j in jsons]
        return {"df": pd.DataFrame(jsons)}
    
@component
class CombineData:
    
    @component.output_types(df=pd.DataFrame)
    
    def run(self, llm: pd.DataFrame, docs: list[Document]):
        meta = {}
        for k in docs[0].meta.keys():
            meta[k] = [d.meta[k] for d in docs]
            
        meta = pd.DataFrame(meta)
        
        # res = pd.concat([llm, meta], axis=1).assign(date = lambda x: pd.to_datetime(x.date, format="%d %B %Y"))
        res = pd.concat([llm, meta], axis=1).assign(date = lambda x: pd.to_datetime(x.date, format="mixed"))
        return {"df": res}
    
@component
class DocumentsMetaToPandas:
    
    @component.output_types(df=pd.DataFrame)
    
    def run(self, documents: list[Document]) -> pd.DataFrame:
        
        data_as_dict = {}
        for k in documents[0].meta.keys():
            data_as_dict[k] = [d.meta[k] for d in documents]
            
        return {"df": data_as_dict}
    
@component
class ForEachPromptBuilder:
    def __init__(self, template: str):
        self.template = template
        ast = Template(template).environment.parse(template)
        template_variables = meta.find_undeclared_variables(ast)
        variables = list(template_variables)
        variables = variables or []
        
        for var in variables:
            component.set_input_type(self, var, Any, "")
        
    def convert_kwargs_to_list_of_dicts(self, _lengths, **kwargs):
        res = []
        for i in range(_lengths[0]):
            res.append({k:v[i] for k, v in kwargs.items()})
        return res
    
    @component.output_types(prompts=list[str])
    def run(self, **kwargs):
        # At least one kwarg needs to be provided, otherwise what is the point?
        if len(kwargs) == 0:
            raise ValueError("At least one kwarg needs to be provided.")
        
        # Validate that all the kwargs provided are the same length
        lengths = list(set([len(v) for k, v in kwargs.items()]))
        if len(lengths) > 1:
            raise ValueError("Lists provided as arguments are not the same length. Ensure that each of the **kwargs provided is a list of equal length.")
        
        prompt_arguments = self.convert_kwargs_to_list_of_dicts(_lengths=lengths, **kwargs)
        
        res = []
        for p in prompt_arguments:
            builder = PromptBuilder(self.template).run(**p)
            res.append(builder["prompt"])
            
        return {"prompts": res}
    
@component
class ForEach_OllamaLLMTaskRunner2:
    def __init__(
            self, 
            model_name: str, 
            ollama_endpoint: str, 
            include_meta: bool=False, 
            system_prompt: str | None=None,
            generation_kwargs: dict[str, any] | None=None
        ):
        self.generator = OllamaGenerator(
                            model=model_name,
                            url=f"{ollama_endpoint}/api/generate",
                            system_prompt=system_prompt,
                            generation_kwargs=generation_kwargs
                        )
        self.include_meta = include_meta
        
    @component.output_types(replies=list[str])
    def run(self, prompts: list[str]):
        replies = []
        for p in tqdm(prompts):
            replies.append(self.generator.run(p))
        
        if not self.include_meta:
            res = [" ".join(r["replies"]) for r in replies]
        else:
            res = replies
        return {"replies": res}