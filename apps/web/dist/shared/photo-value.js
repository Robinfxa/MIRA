/** Application-only immutable resource identity; never interpret a URL or a loose prefix. */
export function generatedPhotoIdentity(value) {
    const match = /^generated_story_photo:v1:([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}):([0-9a-f]{64})$/.exec(value);
    return match ? Object.freeze({ resourceId: match[1], contentDigest: match[2] }) : null;
}
export function isPhotoValue(value) {
    return value === 'trip_photo' || value === 'trip_photo_placeholder' || generatedPhotoIdentity(value) !== null;
}
