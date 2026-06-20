"""
Job — scraped job listing from BOSS Zhipin.
"""

import hashlib
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

# 职位(Job)数据模型，表示从BOSS直聘抓取到的职位信息
class Job(BaseModel):
    # 职位唯一ID，可由公司名和职位名生成MD5哈希
    id: str = ""
    # 职位名称
    title: str
    # 公司名称
    company: str
    # 薪资范围，例如 "20-30K"
    salary: str
    # 工作城市
    city: str
    # 职位描述
    description: str
    # 职位详情页面URL
    url: str
    # 抓取时间，默认为创建实例时的当前时间
    scraped_at: datetime = Field(default_factory=datetime.now)

    # 在模型校验后自动生成ID（如果未指定），确保每条数据有唯一标识
    # 例如：Job(title="Python后端开发", company="字节跳动", ...) 会自动生成唯一ID
    @model_validator(mode="after")
    def _compute_id(self) -> "Job":
        # 如果ID未提供，根据公司和职位名生成MD5哈希作为唯一ID
        if not self.id:
            self.id = hashlib.md5(f"{self.company}{self.title}".encode()).hexdigest()
        return self

    # 静态方法，用于外部直接基于公司名和职位名生成对应的ID
    @staticmethod
    def compute_id(company: str, title: str) -> str:
        # 返回公司名+职位名拼接后的MD5哈希字符串
        return hashlib.md5(f"{company}{title}".encode()).hexdigest()
