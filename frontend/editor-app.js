import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import Link from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import Underline from '@tiptap/extension-underline'
import Image from '@tiptap/extension-image'
import TurndownService from 'turndown'
import { gfm } from 'turndown-plugin-gfm'

const seed = window.__studioEditorSeed
if (!seed) {
  // Non-editor routes also include the global shell script, so we no-op here.
} else {
  const form = document.getElementById('studio-editor-form')
  const titleInput = document.getElementById('editor-title')
  const subtitleInput = document.getElementById('editor-subtitle')
  const slugInput = document.getElementById('editor-slug')
  const statusInput = document.getElementById('editor-status')
  const tagsInput = document.getElementById('editor-tags')
  const categoriesInput = document.getElementById('editor-categories')
  const publishedAtInput = document.getElementById('editor-published-at')
  const coverImagePathInput = document.getElementById('editor-cover-image-path')
  const coverPreviewNode = document.getElementById('editor-cover-preview')
  const coverUploadButton = document.getElementById('editor-upload-cover')
  const hiddenCoverImagePathInput = document.getElementById('editor-cover-image-input')
  const hiddenEditorJsonInput = document.getElementById('editor-json-input')
  const hiddenMarkdownInput = document.getElementById('editor-markdown-input')
  const hiddenHtmlInput = document.getElementById('editor-html-input')
  const editorImageUploadInput = document.getElementById('editor-image-upload')
  const editorCoverUploadInput = document.getElementById('editor-cover-upload')
  const previewNode = document.getElementById('editor-preview')
  const frontmatterNode = document.getElementById('frontmatter-preview')
  const autosaveState = document.getElementById('editor-autosave-state')
  const lastSavedNode = document.getElementById('editor-last-saved')
  const previewToggle = document.getElementById('editor-toggle-preview')
  const focusToggle = document.getElementById('editor-toggle-focus')
  const writerShell = document.querySelector('.writer-shell')
  const exportMarkdownButton = document.getElementById('editor-export-markdown')
  const exportHtmlButton = document.getElementById('editor-export-html')
  const toolbar = document.getElementById('editor-toolbar')
  const editorColumn = document.querySelector('.editor-column')
  const channelInputs = Array.from(document.querySelectorAll('input[name="channels"]'))

  const turndown = new TurndownService({
    headingStyle: 'atx',
    codeBlockStyle: 'fenced',
    bulletListMarker: '-',
    emDelimiter: '*',
  })
  turndown.use(gfm)

  let slugTouched = Boolean(slugInput?.value)
  let autosaveTimer = null
  let lastSavedAt = seed.updated_at || ''
  let saveCounter = 0
  let dragDepth = 0

  const slugify = (value) => value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')

  const yamlString = (value) => JSON.stringify(value || '')
  const yamlArray = (values) => {
    if (!values.length) return '[]'
    return `[${values.map((item) => JSON.stringify(item)).join(', ')}]`
  }

  const getChannels = () => channelInputs.filter((input) => input.checked).map((input) => input.value)
  const getTags = () => (tagsInput?.value || '').split(',').map((item) => item.trim()).filter(Boolean)
  const getCategories = () => (categoriesInput?.value || '').split(',').map((item) => item.trim()).filter(Boolean)
  const currentTitle = () => titleInput?.value?.trim() || 'Untitled'
  const currentSlug = () => slugInput?.value?.trim() || slugify(currentTitle()) || 'untitled'

  const setAutosaveState = (message, tone = 'idle') => {
    if (!autosaveState) return
    autosaveState.textContent = message
    autosaveState.classList.remove('status-ok', 'status-warn', 'status-bad')
    if (tone === 'ok') autosaveState.classList.add('status-ok')
    if (tone === 'warn') autosaveState.classList.add('status-warn')
    if (tone === 'bad') autosaveState.classList.add('status-bad')
  }

  const setLastSaved = (value) => {
    lastSavedAt = value || lastSavedAt || ''
    if (lastSavedNode) {
      lastSavedNode.innerHTML = `Last saved: <code>${lastSavedAt || 'Not saved yet'}</code>`
    }
  }

  const updateFrontmatterPreview = () => {
    if (!frontmatterNode) return
    frontmatterNode.textContent = [
      '---',
      `title: ${currentTitle()}`,
      `subtitle: ${subtitleInput?.value?.trim() || ''}`,
      `status: ${statusInput?.value || 'draft'}`,
      `channels: ${yamlArray(getChannels())}`,
      `tags: ${yamlArray(getTags())}`,
      `categories: ${yamlArray(getCategories())}`,
      `created_at: ${seed.created_at || ''}`,
      `updated_at: ${lastSavedAt || ''}`,
      `published_at: ${publishedAtInput?.value?.trim() || ''}`,
      `cover_image_path: ${coverImagePathInput?.value?.trim() || ''}`,
      `linkedin_post_urn: ${seed.linkedin_post_urn || ''}`,
      `instagram_media_id: ${seed.instagram_media_id || ''}`,
      `substack_post_id: ${seed.substack_post_id || ''}`,
      `x_post_id: ${seed.x_post_id || ''}`,
      '---',
    ].join('\n')
  }

  const buildFrontmatterMarkdown = (bodyMarkdown) => {
    return [
      '---',
      `title: ${yamlString(currentTitle())}`,
      `subtitle: ${yamlString(subtitleInput?.value?.trim() || '')}`,
      `status: ${statusInput?.value || 'draft'}`,
      `channels: ${yamlArray(getChannels())}`,
      `tags: ${yamlArray(getTags())}`,
      `categories: ${yamlArray(getCategories())}`,
      `created_at: ${yamlString(seed.created_at || '')}`,
      `updated_at: ${yamlString(lastSavedAt || '')}`,
      `published_at: ${yamlString(publishedAtInput?.value?.trim() || '')}`,
      `cover_image_path: ${yamlString(coverImagePathInput?.value?.trim() || '')}`,
      `linkedin_post_urn: ${yamlString(seed.linkedin_post_urn || '')}`,
      `instagram_media_id: ${yamlString(seed.instagram_media_id || '')}`,
      `substack_post_id: ${yamlString(seed.substack_post_id || '')}`,
      `x_post_id: ${yamlString(seed.x_post_id || '')}`,
      '---',
      '',
      bodyMarkdown.trimEnd(),
      '',
    ].join('\n')
  }

  const setCoverPreview = (url, label = 'Cover preview') => {
    if (!coverPreviewNode) return
    if (!url) {
      coverPreviewNode.innerHTML = '<div class="cover-preview-empty">No cover selected yet.</div>'
      return
    }
    coverPreviewNode.innerHTML = `<img src="${url}" alt="${label}" class="cover-preview-image" />`
  }

  const updateHiddenFields = () => {
    const html = editor.getHTML()
    const markdown = turndown.turndown(html).trim()
    hiddenEditorJsonInput.value = JSON.stringify(editor.getJSON())
    hiddenHtmlInput.value = html
    hiddenMarkdownInput.value = markdown
    hiddenCoverImagePathInput.value = coverImagePathInput?.value?.trim() || ''
    if (previewNode) previewNode.innerHTML = html || '<p><em>Nothing to preview yet.</em></p>'
    updateFrontmatterPreview()
    return { html, markdown }
  }

  const updateFocusButtonLabel = () => {
    if (!focusToggle) return
    focusToggle.textContent = document.body.classList.contains('editor-focus-mode') ? 'Exit focus' : 'Focus mode'
  }

  const downloadBlob = (filename, content, type) => {
    const blob = new Blob([content], { type })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  const collectAutosaveForm = () => {
    updateHiddenFields()
    const payload = new URLSearchParams()
    payload.set('return_to', '/editor')
    payload.set('content_id', form.querySelector('input[name="content_id"]').value || '')
    payload.set('previous_slug', form.querySelector('input[name="previous_slug"]').value || '')
    payload.set('title', currentTitle())
    payload.set('subtitle', subtitleInput?.value || '')
    payload.set('slug', currentSlug())
    payload.set('status', statusInput?.value || 'draft')
    payload.set('tags', tagsInput?.value || '')
    payload.set('categories', categoriesInput?.value || '')
    payload.set('published_at', publishedAtInput?.value || '')
    payload.set('editor_json', hiddenEditorJsonInput.value)
    payload.set('markdown_body', hiddenMarkdownInput.value)
    payload.set('html_body', hiddenHtmlInput.value)
    payload.set('cover_image_path', hiddenCoverImagePathInput.value)
    getChannels().forEach((channel) => payload.append('channels', channel))
    return payload
  }

  const autosave = async () => {
    const requestId = ++saveCounter
    setAutosaveState('Autosaving...', 'warn')
    try {
      const response = await fetch('/editor/autosave', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
        body: collectAutosaveForm().toString(),
      })
      if (!response.ok) throw new Error(`Autosave failed: ${response.status}`)
      const data = await response.json()
      if (requestId !== saveCounter) return
      if (data.content_id) {
        form.querySelector('input[name="content_id"]').value = data.content_id
        seed.id = data.content_id
      }
      if (data.slug) {
        form.querySelector('input[name="previous_slug"]').value = data.slug
        if (currentSlug() !== data.slug) slugInput.value = data.slug
        const url = new URL(window.location.href)
        url.searchParams.set('content', data.content_id || data.slug)
        window.history.replaceState({}, '', url)
      }
      setLastSaved(data.updated_at || new Date().toISOString())
      setAutosaveState('Autosaved locally', 'ok')
    } catch (error) {
      console.error(error)
      setAutosaveState('Autosave failed. Your draft is still in the browser.', 'bad')
    }
  }

  const uploadImageFile = async (file) => {
    const payload = new FormData()
    payload.set('slug', currentSlug())
    payload.set('title', currentTitle())
    payload.set('image', file, file.name)
    const response = await fetch('/editor/upload-image', {
      method: 'POST',
      body: payload,
    })
    if (!response.ok) throw new Error(`Image upload failed: ${response.status}`)
    return response.json()
  }

  const insertUploadedImage = async (file) => {
    setAutosaveState('Uploading image...', 'warn')
    const data = await uploadImageFile(file)
    editor.chain().focus().setImage({ src: data.public_url }).run()
    setAutosaveState('Image uploaded into draft', 'ok')
    queueAutosave()
    return data
  }

  const queueAutosave = () => {
    setAutosaveState('Changes pending...', 'warn')
    window.clearTimeout(autosaveTimer)
    autosaveTimer = window.setTimeout(autosave, 1500)
  }

  const initialContent = seed.editor_json && Array.isArray(seed.editor_json.content) && seed.editor_json.content.length
    ? seed.editor_json
    : (seed.html_body && seed.html_body.trim() ? seed.html_body : '<p></p>')

  const editor = new Editor({
    element: document.getElementById('tiptap-editor'),
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
      }),
      Underline,
      Link.configure({
        openOnClick: false,
        autolink: true,
        linkOnPaste: true,
      }),
      Image,
      Placeholder.configure({
        placeholder: 'Write here first. Publish later. Keep the craft local.',
      }),
    ],
    content: initialContent,
    editorProps: {
      attributes: {
        class: 'ProseMirror studio-prosemirror',
      },
    },
    autofocus: false,
    onCreate() {
      updateHiddenFields()
      updateToolbarState()
      updateFrontmatterPreview()
      setLastSaved(seed.updated_at || '')
    },
    onSelectionUpdate() {
      updateToolbarState()
    },
    onUpdate() {
      updateHiddenFields()
      updateToolbarState()
      queueAutosave()
    },
  })

  const toolbarActions = {
    bold: () => editor.chain().focus().toggleBold().run(),
    italic: () => editor.chain().focus().toggleItalic().run(),
    underline: () => editor.chain().focus().toggleUnderline().run(),
    h2: () => editor.chain().focus().toggleHeading({ level: 2 }).run(),
    h3: () => editor.chain().focus().toggleHeading({ level: 3 }).run(),
    bulletList: () => editor.chain().focus().toggleBulletList().run(),
    orderedList: () => editor.chain().focus().toggleOrderedList().run(),
    blockquote: () => editor.chain().focus().toggleBlockquote().run(),
    codeBlock: () => editor.chain().focus().toggleCodeBlock().run(),
    horizontalRule: () => editor.chain().focus().setHorizontalRule().run(),
    link: () => {
      const existing = editor.getAttributes('link').href || ''
      const href = window.prompt('Link URL', existing)
      if (href === null) return
      if (!href.trim()) {
        editor.chain().focus().unsetLink().run()
        return
      }
      editor.chain().focus().extendMarkRange('link').setLink({ href: href.trim() }).run()
    },
    'image-upload': () => {
      editorImageUploadInput?.click()
    },
  }

  const toolbarState = {
    bold: () => editor.isActive('bold'),
    italic: () => editor.isActive('italic'),
    underline: () => editor.isActive('underline'),
    h2: () => editor.isActive('heading', { level: 2 }),
    h3: () => editor.isActive('heading', { level: 3 }),
    bulletList: () => editor.isActive('bulletList'),
    orderedList: () => editor.isActive('orderedList'),
    blockquote: () => editor.isActive('blockquote'),
    codeBlock: () => editor.isActive('codeBlock'),
    link: () => editor.isActive('link'),
  }

  const updateToolbarState = () => {
    toolbar?.querySelectorAll('button[data-action]').forEach((button) => {
      const action = button.dataset.action
      const checker = toolbarState[action]
      button.classList.toggle('is-active', Boolean(checker?.()))
    })
  }

  toolbar?.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]')
    if (!button) return
    const action = button.dataset.action
    toolbarActions[action]?.()
    updateToolbarState()
  })

  titleInput?.addEventListener('input', () => {
    if (slugInput && !slugTouched) slugInput.value = slugify(titleInput.value)
    updateFrontmatterPreview()
    queueAutosave()
  })
  slugInput?.addEventListener('input', () => {
    slugTouched = true
    queueAutosave()
  })
  ;[subtitleInput, statusInput, tagsInput, categoriesInput, publishedAtInput, coverImagePathInput].forEach((input) => {
    input?.addEventListener('input', () => {
      updateFrontmatterPreview()
      updateHiddenFields()
      queueAutosave()
    })
  })
  channelInputs.forEach((input) => input.addEventListener('change', () => {
    updateFrontmatterPreview()
    queueAutosave()
  }))

  coverUploadButton?.addEventListener('click', () => {
    editorCoverUploadInput?.click()
  })

  editorImageUploadInput?.addEventListener('change', async () => {
    const file = editorImageUploadInput.files?.[0]
    if (!file) return
    setAutosaveState('Uploading image...', 'warn')
    try {
      const data = await uploadImageFile(file)
      editor.chain().focus().setImage({ src: data.public_url }).run()
      setAutosaveState('Image uploaded into draft', 'ok')
      queueAutosave()
    } catch (error) {
      console.error(error)
      setAutosaveState('Image upload failed.', 'bad')
    } finally {
      editorImageUploadInput.value = ''
    }
  })

  editorCoverUploadInput?.addEventListener('change', async () => {
    const file = editorCoverUploadInput.files?.[0]
    if (!file) return
    setAutosaveState('Uploading cover image...', 'warn')
    try {
      const data = await uploadImageFile(file)
      const coverAsset = data.content_asset || data.public_url
      coverImagePathInput.value = coverAsset
      hiddenCoverImagePathInput.value = coverAsset
      setCoverPreview(data.public_url, 'Cover image')
      updateFrontmatterPreview()
      setAutosaveState('Cover image uploaded', 'ok')
      queueAutosave()
    } catch (error) {
      console.error(error)
      setAutosaveState('Cover upload failed.', 'bad')
    } finally {
      editorCoverUploadInput.value = ''
    }
  })

  previewToggle?.addEventListener('click', () => {
    writerShell?.classList.toggle('preview-mode')
    previewToggle.textContent = writerShell?.classList.contains('preview-mode') ? 'Back to editor' : 'Preview mode'
  })

  focusToggle?.addEventListener('click', () => {
    document.body.classList.toggle('editor-focus-mode')
    window.localStorage.setItem('socialmediamanager.editor.focus', document.body.classList.contains('editor-focus-mode') ? 'true' : 'false')
    updateFocusButtonLabel()
  })

  exportMarkdownButton?.addEventListener('click', () => {
    const { markdown } = updateHiddenFields()
    downloadBlob(`${currentSlug() || 'draft'}.md`, buildFrontmatterMarkdown(markdown), 'text/markdown;charset=utf-8')
  })

  exportHtmlButton?.addEventListener('click', () => {
    const { html } = updateHiddenFields()
    downloadBlob(`${currentSlug() || 'draft'}.html`, html, 'text/html;charset=utf-8')
  })

  form?.addEventListener('submit', () => {
    updateHiddenFields()
    hiddenCoverImagePathInput.value = coverImagePathInput?.value?.trim() || ''
    if (slugInput && !slugInput.value.trim()) slugInput.value = currentSlug()
    if (autosaveTimer) window.clearTimeout(autosaveTimer)
    setAutosaveState('Saving draft...', 'warn')
  })

  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault()
      updateHiddenFields()
      form?.requestSubmit(form.querySelector('button[type="submit"]'))
    }
  })

  editorColumn?.addEventListener('dragenter', (event) => {
    if (!Array.from(event.dataTransfer?.types || []).includes('Files')) return
    dragDepth += 1
    editorColumn.classList.add('drag-over')
  })

  editorColumn?.addEventListener('dragover', (event) => {
    if (!Array.from(event.dataTransfer?.types || []).includes('Files')) return
    event.preventDefault()
  })

  editorColumn?.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1)
    if (dragDepth === 0) editorColumn.classList.remove('drag-over')
  })

  editorColumn?.addEventListener('drop', async (event) => {
    if (!Array.from(event.dataTransfer?.types || []).includes('Files')) return
    event.preventDefault()
    dragDepth = 0
    editorColumn.classList.remove('drag-over')
    const files = Array.from(event.dataTransfer?.files || []).filter((file) => file.type.startsWith('image/'))
    if (!files.length) return
    try {
      for (const file of files) {
        await insertUploadedImage(file)
      }
    } catch (error) {
      console.error(error)
      setAutosaveState('Image drop failed.', 'bad')
    }
  })

  editor.view.dom.addEventListener('paste', async (event) => {
    const files = Array.from(event.clipboardData?.files || []).filter((file) => file.type.startsWith('image/'))
    if (!files.length) return
    event.preventDefault()
    try {
      for (const file of files) {
        await insertUploadedImage(file)
      }
    } catch (error) {
      console.error(error)
      setAutosaveState('Pasted image failed.', 'bad')
    }
  })

  setCoverPreview(
    coverImagePathInput?.value?.trim()
      ? `/content-files/${coverImagePathInput.value.trim().replace(/^\.?\/*content\/drafts\//, '')}`
      : '',
  )
  if (window.localStorage.getItem('socialmediamanager.editor.focus') === 'true') {
    document.body.classList.add('editor-focus-mode')
  }
  updateFocusButtonLabel()
}
