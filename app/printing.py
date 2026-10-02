"""Print-job orchestration shared by Studio and the image webhook."""
from contextlib import contextmanager
from flask import current_app
from app import printer_service
from app.label_store import directory, write_json
from app.labeldesigner.printer import PrinterQueue
from app.rendering import render
from app.validation import InputError


class PrintFailure(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


@contextmanager
def printing_session(queue):
    with printer_service.printer_lock() as acquired:
        if not acquired:
            raise PrintFailure('Printer busy', 409)
        yield queue


def check_media(queue, *, confirm_red=False, batch=False):
    if queue.device_specifier == 'simulation':
        return
    state = printer_service.status_locked(queue.device_specifier, queue.label_size, model=queue.model)
    if state['state'] != 'ready':
        raise PrintFailure(state['message'], 503)
    if queue.label_size == '62red' and state.get('mediaColor') != 'black-red':
        if batch:
            raise InputError('Load detected black/red tape before bulk printing.')
        if not confirm_red:
            raise InputError('Confirm that 62 mm black/red tape is loaded before printing.')


def submit(queue):
    try:
        error = queue.process_queue()
    except ValueError as error:
        raise InputError(str(error)) from error
    except Exception as error:
        raise PrintFailure(str(error)) from error
    if error:
        raise PrintFailure(error)


def print_drafts(entries, cut, *, job_id=None, confirm_red=False):
    paper = {(draft['sizeId'], draft['highRes']) for draft, _ in entries}
    if len(paper) != 1:
        raise InputError('All labels in a batch must use the same paper and resolution.')
    size, high_res = next(iter(paper))
    selected_device = printer_service.device()
    queue = PrinterQueue(current_app.config['PRINTER_MODEL'], selected_device, size)
    with printing_session(queue):
        record = None
        if job_id:
            jobs = directory().parent / 'bulk-jobs'
            jobs.mkdir(exist_ok=True)
            record = jobs / (job_id + '.json')
            if record.exists():
                raise PrintFailure('This batch was already submitted. Check the printed labels before starting another batch.', 409)
        check_media(queue, confirm_red=confirm_red, batch=bool(job_id))
        total_pixels = 0
        for number, (draft, image_bytes) in enumerate(entries, 1):
            try:
                label = render(draft, image_bytes)
                if job_id:
                    rendered = label.generate(rotate=False)
                    total_pixels += rendered.width * rendered.height
                    if total_pixels > 64_000_000:
                        raise InputError('Batch images are too large. Select fewer labels.')
                    label.generate = lambda rotate=False, image=rendered: image
                queue.add_label_to_queue(label, cut == 'each' or number == len(entries), high_res)
            except Exception as error:
                prefix = f'Label {number}: ' if job_id else ''
                raise InputError(f'{prefix}{error}. No labels were sent.') from error
        if job_id:
            try:
                queue.validate_queue()
            except Exception as error:
                raise InputError(f'Printer conversion failed: {error}. No labels were sent.') from error
            write_json(record, {'state': 'submitted', 'count': len(entries)})
        try:
            submit(queue)
        except PrintFailure as error:
            if job_id:
                raise PrintFailure(f'Printing stopped: {error}. Some labels may have printed. Check the printer before starting another batch.') from error
            raise
        if record:
            write_json(record, {'state': 'complete', 'count': len(entries)})
    kind = 'simulated' if selected_device == 'simulation' else 'printed'
    message = 'Batch complete' if job_id else 'Test image saved' if kind == 'simulated' else 'Printed'
    return {'kind': kind, 'copies': len(entries), 'message': message}


def print_image_queue(queue):
    """Keep the webhook request format while applying the same printer safeguards."""
    queue.device_specifier = printer_service.device(queue.device_specifier)
    with printing_session(queue):
        check_media(queue)
        submit(queue)
