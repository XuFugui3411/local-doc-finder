async (page) => {
  const errors=[];
  page.on('pageerror', error=>errors.push(error.message));
  await page.getByRole('textbox',{name:'资料目录路径'}).fill('D:\\coding\\local-doc-finder\\output\\demo-documents');
  await page.getByRole('button',{name:'建立 / 更新索引',exact:true}).click();
  await page.getByText('索引已更新',{exact:true}).waitFor({timeout:45000});
  await page.getByRole('textbox',{name:'搜索文件名或正文'}).fill('wordcheck 三万元');
  await page.getByRole('button',{name:'搜索文档',exact:true}).click();
  await page.getByText('找到 1 份文档',{exact:true}).waitFor();
  await page.getByRole('button',{name:'DOCX',exact:true}).click();
  await page.getByText('找到 1 份文档',{exact:true}).waitFor();
  const body=await page.locator('.result').innerText();
  if(!body.includes('正文段落 1')||!body.includes('表格 1 · 第 1 行')||body.includes('PDF 第'))throw new Error('Incorrect DOCX location labels');
  await page.setViewportSize({width:1440,height:1000});
  await page.screenshot({path:'output/playwright/docx-search.png',fullPage:true});
  const [reader]=await Promise.all([page.waitForEvent('popup'),page.locator('.snippet-label').filter({hasText:'表格 1 · 第 1 行'}).click()]);
  await reader.waitForLoadState('domcontentloaded');
  if(!reader.url().endsWith('#block-2'))throw new Error('DOCX text-block anchor lost');
  if(!(await reader.locator('#block-2').innerText()).includes('三万元'))throw new Error('DOCX table context lost');
  await reader.getByText('下载原 DOCX，用 Word / WPS 查看完整排版',{exact:true}).waitFor();
  await reader.screenshot({path:'output/playwright/docx-reader.png',fullPage:true});
  await reader.close();
  await page.setViewportSize({width:390,height:844});
  if(!await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth))throw new Error('Mobile DOCX layout overflow');
  await page.screenshot({path:'output/playwright/docx-mobile.png',fullPage:true});
  if(errors.length)throw new Error(errors.join('\n'));
  return {ok:true,checks:['index DOCX','paragraph/table AND','DOCX filter','location labels','reader anchor','download entry','390px layout']};
}
