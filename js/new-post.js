document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM Content Loaded');

    // 检查必要的元素是否存在
    const editor_textarea = document.getElementById("editor");
    const preview_pane = document.getElementById("preview-pane");
    const theme_toggle = document.getElementById("theme-toggle");
    
    if (!editor_textarea) {
        console.error('Editor textarea not found');
        return;
    }
    if (!preview_pane) {
        console.error('Preview pane not found');
        return;
    }
    if (!theme_toggle) {
        console.error('Theme toggle button not found');
        return;
    }

    // 初始化编辑器
    try {
        console.log('Initializing CodeMirror');
        var editor = CodeMirror.fromTextArea(editor_textarea, {
            mode: 'markdown',
            theme: 'default',
            lineNumbers: true,
            lineWrapping: true,
            extraKeys: {"Enter": "newlineAndIndentContinueMarkdownList"},
            autofocus: true
        });
        console.log('CodeMirror initialized successfully');
    } catch (e) {
        console.error('Failed to initialize CodeMirror:', e);
        return;
    }

    // 实时预览功能
    function updatePreview() {
        console.log('Updating preview');
        var content = editor.getValue();
        try {
            if (typeof marked === 'function') {
                preview_pane.innerHTML = marked(content);
            } else if (typeof marked === 'object' && typeof marked.parse === 'function') {
                preview_pane.innerHTML = marked.parse(content);
            } else {
                console.error('Marked.js not properly initialized');
                preview_pane.innerHTML = '<p>Preview not available</p>';
            }
        } catch (e) {
            console.error('Preview update failed:', e);
            preview_pane.innerHTML = '<p>Preview failed</p>';
        }
    }

    // 防抖函数
    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    // 监听编辑器变化
    console.log('Setting up editor change listener');
    editor.on('change', debounce(function() {
        updatePreview();
    }, 300));

    // 主题切换
    console.log('Setting up theme toggle');
    let isDarkMode = false;
    theme_toggle.addEventListener('click', function() {
        console.log('Theme toggle clicked');
        isDarkMode = !isDarkMode;
        if (isDarkMode) {
            document.body.classList.add('theme-dark');
            editor.setOption('theme', 'material-darker');
            theme_toggle.querySelector('i').classList.replace('fa-moon', 'fa-sun');
        } else {
            document.body.classList.remove('theme-dark');
            editor.setOption('theme', 'default');
            theme_toggle.querySelector('i').classList.replace('fa-sun', 'fa-moon');
        }
    });

    // 保存草稿按钮点击事件
    document.getElementById('save-draft').addEventListener('click', function() {
        try {
            // 获取当前内容
            const content = editor.getValue();
            const title = document.getElementById('post-title').value;
            const tags = document.getElementById('post-tags').value;
            
            // 保存到 localStorage
            localStorage.setItem('draft_content', content);
            localStorage.setItem('draft_title', title);
            localStorage.setItem('draft_tags', tags);
            
            // 显示保存成功提示
            alert('草稿已保存');
        } catch (e) {
            console.error('保存草稿失败:', e);
            alert('保存草稿失败');
        }
    });

    // 返回首页按钮点击事件
    document.getElementById('back-to-home').addEventListener('click', function() {
        // 如果编辑器有内容，提示用户是否保存
        const content = editor.getValue();
        const title = document.getElementById('post-title').value;
        
        if (content || title) {
            if (confirm('是否保存当前编辑的内容？')) {
                // 保存到本地存储
                localStorage.setItem('draft_content', content);
                localStorage.setItem('draft_title', title);
                alert('内容已保存为草稿');
            }
        }
        
        // 跳转到首页
        window.location.href = '/';  // Jekyll 语法，会被替换为实际的 baseurl
    });

    // 发布按钮点击事件
    document.getElementById('publish-post').addEventListener('click', async function() {
        try {
            // 获取内容
            const title = document.getElementById('post-title').value;
            const tags = document.getElementById('post-tags').value;
            const content = editor.getValue();

            // 验证必填字段
            if (!title) {
                alert('请输入博客标题');
                return;
            }

            // 生成文件名和内容
            const date = new Date().toISOString().split('T')[0];
            const fileName = `${date}-${title.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')}.md`;
            const frontMatter = `---
layout: post
title: ${title}
date: ${date}
tags: [${tags}]
---

`;
            const fullContent = frontMatter + content;

            // GitHub API 配置
            const githubToken = config.githubToken;
            const owner = config.owner;
            const repo = config.repo;
            const path = `_posts/${fileName}`;
            const message = `Add new post: ${title}`;

            // 创建文件到 GitHub
            const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents/${path}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `token ${githubToken}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: message,
                    content: btoa(unescape(encodeURIComponent(fullContent))),
                    branch: 'main'
                })
            });

            if (response.ok) {
                // 清除草稿
                localStorage.removeItem('draft_content');
                localStorage.removeItem('draft_title');
                localStorage.removeItem('draft_tags');

                alert('博客已成功发布到 GitHub！');
                
                // 可选：清空编辑器
                if (confirm('是否清空编辑器？')) {
                    editor.setValue('');
                    document.getElementById('post-title').value = '';
                    document.getElementById('post-tags').value = '';
                }
            } else {
                const error = await response.json();
                throw new Error(`GitHub API 错误: ${error.message}`);
            }
        } catch (e) {
            console.error('发布失败:', e);
            alert('发布失败: ' + e.message);
        }
    });

    // 恢复草稿
    try {
        console.log('Restoring draft');
        const savedContent = localStorage.getItem('draft_content');
        const savedTitle = localStorage.getItem('draft_title');
        const savedTags = localStorage.getItem('draft_tags');

        if (savedContent) {
            editor.setValue(savedContent);
        }
        if (savedTitle) document.getElementById('post-title').value = savedTitle;
        if (savedTags) document.getElementById('post-tags').value = savedTags;
        console.log('Draft restored');
    } catch (e) {
        console.error('Failed to restore draft:', e);
    }

    // 等待一小段时间后再执行初始预览
    setTimeout(() => {
        updatePreview();
        console.log('Initial preview updated');
    }, 500);
});