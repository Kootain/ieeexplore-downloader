#!/usr/bin/env python
'''
Created on 2018-5-4
@author: Kootain
'''
import httplib, ssl, urllib2, socket
import cookielib
import re
import json
import os
import sys
import configparser

cf = configparser.ConfigParser()
cf.read('config.conf')

if cf.getboolean('task', 'upload_cos'):
    from qcloud_cos import CosConfig
    from qcloud_cos import CosS3Client


class Paper(object):
    BASE_URL = 'https://ieeexplore.ieee.org'

    def __init__(self, json_str, cookie):
        paper_data = json.loads(json_str)
        self.id = paper_data['articleId']
        self.pdf = paper_data['pdfPath']
        self.title = paper_data['title']
        self.abstract = paper_data['abstract']
        self.cookie = cookie

    def get_pdf_url(self):
        return Paper.BASE_URL + self.pdf.replace("iel7", "ielx7", 1)

    def get_pdf_file_name(self):
        return self.title.replace(':', '-')


class CosClient(object):
    def __init__(self):
        secret_id = cf.get('cos', 'secret_id')
        secret_key = cf.get('cos', 'secret_key')
        region = cf.get('cos', 'region')
        self.config = CosConfig(Secret_id=secret_id, Secret_key=secret_key, Region=region)
        self.client = CosS3Client(self.config)
        self.bucket_name = str(cf.get('cos', 'bucket_name'))

    def upload_paper(self, paper, pdf):
        self.client.put_object(
            Bucket=self.bucket_name,
            Body=pdf,
            Key=cf.get('upload_cos', 'paper_path') + paper.get_pdf_file_name() + '.pdf',
            StorageClass='STANDARD',
            ContentType='application/pdf; charset=utf-8'
        )

        self.client.put_object(
            Bucket=self.bucket_name,
            Body=pdf,
            Key=cf.get('upload_cos', 'data_path') + str(paper.id) + '.pdf',
            StorageClass='STANDARD',
            ContentType='application/pdf; charset=utf-8'
        )

class Downloader(object):

    PAPER_DETAIL_URL = 'https://ieeexplore.ieee.org/document/'
    PAPER_DETAIL_REG = 'global\.document\.metadata=({.*?});\n'
    PDF_CHECK_PREFIX = '<!DOCTYPE html>'

    def __init__(self, path=os.getcwd()):
        if path == '':
            path=os.getcwd()
        if not path.endswith("/"):
            path += '/'
        self.download_path = path
        self.cos_client = None
        if cf.getboolean('task', 'upload_cos'):
            self.cos_client = CosClient()


    def __build_opener(self, cookies=cookielib.CookieJar()):
        cookie_handler = urllib2.HTTPCookieProcessor(cookies)
        https_handler = Downloader.HTTPSHandlerV3()
        proxy = cf.get('proxy', 'proxy')
        proxy_handler = urllib2.ProxyHandler({'http': proxy, 'https': proxy})

        opener = urllib2.build_opener(cookie_handler, https_handler, proxy_handler)
        opener.addheaders = self.__fake_header()
        return opener, cookies

    def __fake_header(self):
        return [("User-Agent",
                 "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/535.11 (KHTML, like Gecko) Chrome/17.0.963.56 Safari/535.11"),
                ("Host", "ieeexplore.ieee.org")]

    def __check_file(self, pdf):
        return not pdf.startswith(Downloader.PDF_CHECK_PREFIX)

    def get_paper(self, paper_id):
        opener, cookies = self.__build_opener()
        try:
            page = opener.open(Downloader.PAPER_DETAIL_URL + str(paper_id))
        except Exception as e:
            print ('[Network Error] Url: ' + Downloader.PAPER_DETAIL_URL + str(paper_id))
            print (e.message)
            return

        page_html = page.read()
        paper_json = re.findall(Downloader.PAPER_DETAIL_REG, page_html, re.IGNORECASE)
        if len(paper_json) > 0:
            paper = Paper(paper_json[0], cookies)
        return paper

    def download_paper(self, paper):
        opener, cookie = self.__build_opener(paper.cookie)
        page = opener.open(paper.get_pdf_url())
        pdf = page.read()
        if not self.__check_file(pdf):
            print('[Proxy Error] Can\'t access pdf file, please check your proxy.')
            sys.exit(0)
        f = open(self.download_path + paper.get_pdf_file_name() + '.pdf', "wb")
        f.write(pdf)
        f.close()

        if cf.getboolean('task', 'upload_cos'):
            self.cos_client.upload_paper(paper, pdf)

    def test_proxy(self):
        opener, cookie = self.__build_opener()
        page = opener.open("http://ip.chinaz.com/getip.aspx")
        print(page.read())

    class HTTPSConnectionV3(httplib.HTTPSConnection):
        def __init__(self, *args, **kwargs):
            httplib.HTTPSConnection.__init__(self, *args, **kwargs)

        def connect(self):
            sock = socket.create_connection((self.host, self.port), self.timeout)
            if self._tunnel_host:
                self.sock = sock
                self._tunnel()
            try:
                self.sock = ssl.wrap_socket(sock, self.key_file, self.cert_file, ssl_version=ssl.PROTOCOL_TLSv1_2)
            except ssl.SSLError as e:
                raise e

    class HTTPSHandlerV3(urllib2.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(Downloader.HTTPSConnectionV3, req)

def test_proxy(opener):
    page = opener.open("http://ip.chinaz.com/getip.aspx")
    print(page.read())


if __name__ == '__main__':

    if len(sys.argv) < 2:
        print('usage: ' + sys.argv[0] + ' paper_id')
        sys.exit(0)
    try:
        path = cf.get('task','paper_path')
    except configparser.NoOptionError as e:
        path = os.getcwd()
        print('conf [task] paper_path unset, download to current path: ' + path)
    downloader = Downloader(path)
    downloader.test_proxy()

    paper = downloader.get_paper(sys.argv[1])
    print('downloading <' + paper.title + '> ...')
    downloader.download_paper(paper)
