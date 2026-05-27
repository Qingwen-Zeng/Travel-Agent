# The 200 Travel Chat

A streaming chatbot grounded in the content of The 200 travel blog. v1 is plain LLM; v2 adds retrieval over the blog's content so answers cite real posts.

## Language

### Content sources

**Blog Post**:
A single article published on `the200.blog`. The primary text source for retrieval.
_Avoid_: Article, page, entry.

**Instagram Post**:
A single post on The 200's Instagram. Has a caption (text) and one or more images. Captions are indexed for retrieval; images are not.
_Avoid_: IG post, gram, photo (when referring to the whole post).

**Caption**:
The text body of an [[Instagram Post]]. This is the unit of Instagram content that gets embedded into the vector index.
_Avoid_: Description, copy.

**Photo**:
An image attached to an [[Instagram Post]]. Photos are NOT embedded — they are surfaced as a [[Photo Citation]] when the answer would benefit from a visual reference.
_Avoid_: Image, picture (in spec text; in user-facing copy "photo" and "image" are both fine).

**Photo Citation**:
An external reference (URL to the Instagram post containing the [[Photo]]) that the assistant includes in its answer when a [[Photo]] is relevant. The image itself is not served by this app.
_Avoid_: Image embed, attached photo, inline image — the photo is referenced, not embedded.

### Retrieval units

**Chunk**:
A unit of indexed text — the smallest piece the retriever can return. Has its own embedding vector and source metadata (URL, title, source type). Each [[Caption]] is one Chunk; each [[Blog Post]] yields one Chunk per `<h2>`/`<h3>` section (with long sections sub-split into paragraph-level Chunks).
_Avoid_: Fragment, snippet, passage.

## Flagged ambiguities

- **"Blog"** is overloaded between (a) the public website `the200.blog` and (b) the corpus of [[Blog Post]]s it publishes. In design discussion, prefer "the blog" for the site and "Blog Posts" for the corpus.
- **"Citation"** could mean a text citation (a link to a Blog Post) or a [[Photo Citation]] (a link to an Instagram Post). When unqualified, "citation" defaults to text citations; visual references use the explicit "Photo Citation" term.

## Example dialogue

> **Dev**: When the user asks about beef noodle soup in Taipei, what does the bot return?
>
> **Domain**: It pulls the most relevant Blog Posts and Captions about Taipei food and writes a candid answer in the bot's voice. If one of the Captions came from an Instagram Post with a great photo of the noodle bowl, the answer includes a Photo Citation pointing at that Instagram Post.
>
> **Dev**: So the image isn't shown in the chat — just linked?
>
> **Domain**: Right. The chat is text-only; Photo Citations are external links. The user clicks through to Instagram if they want to see the photo.
