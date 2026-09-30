from DrissionPage import ChromiumPage
from DrissionPage.common import By
from DrissionPage.common import Keys
import pyautogui
import time
import random
import csv
import re

class jd_comment():
    def __init__(self):

        self.page = ChromiumPage('127.0.0.1:9527')
        self.url = 'https://www.jd.com/'
        # self.product_url = 'https://item.jd.com/100278221408.html'
        self.product_url = 'https://npcitem.jd.hk/100142642296.html'


        if 'item.jd.com/' in self.product_url:
            self.page.listen.start('https://api.m.jd.com/client.action')
        elif 'pcitem.jd.hk' in self.product_url:
            self.page.listen.start('https://color.jd.hk/client.action')
        else:
            raise ValueError(f"请自行抓取该商品评论的api: {self.product_url}")

        self.file_ = open('jd1.csv', 'w', encoding='utf-8-sig', newline='')
        self.csv_writer = csv.DictWriter(self.file_, fieldnames=['用户名', '评分', '评论时间', '评论内容'])
        self.csv_writer.writeheader()

    '''整个页面下拉'''
    def drop_down(self):
        for x in range(1, 10, 3):  # 1, 3, 5, 7, 9
            j = x / 9  # 计算滚动比例
            js = 'document.documentElement.scrollTop = document.documentElement.scrollHeight * %f' % j
            self.page.run_js(js)  # 执行 JavaScript 滑动操作
            time.sleep(random.uniform(1, 2))

    '''指定位置滚动'''
    def drop_down2(self,x,y):
        pyautogui.moveTo(x, y, duration=1)
        time.sleep(random.uniform(1, 2))

        for _ in range(7):
            print('下拉')
            pyautogui.scroll(-800)  # 滚动距离，负数表示向下滚动
            time.sleep(random.uniform(0.4, 1))


    '''打开商品详情页'''
    def goto_product_html(self):
        self.page.get(self.product_url)
        time.sleep(random.uniform(3, 4))

    '''点击全部评论'''
    def click_comment_button(self):
        button_flag = self.page.wait.eles_loaded((By.XPATH, '//div[@id="comment"]//div[@class="all-btn"]'),timeout=10)
        print(button_flag)
        if button_flag:
            self.page.ele((By.XPATH, '//div[@id="comment"]//div[@class="all-btn"]')).click()
            time.sleep(random.uniform(3, 4))
        else:
            print('没有找到按钮')


    def main(self):

        '''打开商品详情页'''
        self.goto_product_html()

        '''点击全部评论'''
        self.click_comment_button()
        time.sleep(random.uniform(1, 2))

        div_count = len(self.page.eles((By.XPATH, '//div[@class="_tags_rgt47_12"]/div')))
        print(f"共找到{div_count}个评论筛选标签")

        for i in range(div_count):
            try:
                # 每次重新获取元素，避免引用失效
                divs = self.page.eles((By.XPATH, '//div[@class="_tags_rgt47_12"]/div'))

                div = divs[i]


                div.click()
                print(f"点击第{i + 1}个筛选标签成功")


                time.sleep(random.uniform(1, 2))
                viewport_size = self.page.run_js('''
                    return {
                        width: window.innerWidth,
                        height: window.innerHeight
                    };
                ''')

                current_p = 1
                '''移动到评论窗口位置'''
                # pyautogui.moveTo(1000, 670, duration=1) # 1000(x), 670(y),duration 移动时间 单位秒
                pyautogui.moveTo(viewport_size['width']*0.5, viewport_size['height']*0.55, duration=1)

                while True:
                    try:
                        txt_flag = self.page.ele((By.XPATH, '//div[@id="rateList"]//div[@class="_foldComment_1ygkr_104"]/div'),timeout=0)
                        if txt_flag:
                            print('没有更多了')
                            break
                    except:
                        print('还有评论')

                    if current_p % 10 == 0:
                        time.sleep(random.uniform(2, 3))


                    pyautogui.scroll(-random.randint(900, 1500))  # 滚动距离，负数表示向下滚动
                    time.sleep(random.uniform(2, 4))

                    response_list = self.page.listen.wait(count=1, timeout=5)
                    if response_list:
                        print(f'------------第{current_p}次 接口返回  每次返回1个接口--------------')
                        current_p += 1
                        json_data = response_list.response.body
                        if json_data:
                            try:
                                for data in json_data['result']['floors'][2]['data']:
                                    if not data.get('commentInfo'):
                                        continue
                                    userNickName = data['commentInfo']['userNickName']
                                    score = data['commentInfo']['commentScore']
                                    commentDate = data['commentInfo']['commentDate']
                                    content = data['commentInfo']['commentData']
                                    if content:
                                        content = re.sub(r'\s+', '', content)
                                    dic = {
                                        '用户名': userNickName,
                                        '评分': score,
                                        '评论时间': commentDate,
                                        '评论内容': content
                                    }
                                    self.csv_writer.writerow(dic)
                                    print('数据保存成功', dic)
                            except Exception as e:
                                print('解析出错了', e)
                        else:
                            print('接口没返回数据')

            except Exception as e:
                print(f"第{i + 1}个筛选标签处理失败：{e}")
                continue

            finally:
                time.sleep(random.randint(5, 10))

        print('程序结束')
        self.file_.close()
        self.page.quit()


if __name__ == '__main__':
    jd = jd_comment()
    jd.main()

