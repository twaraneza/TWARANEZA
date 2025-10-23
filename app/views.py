from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages
from .models import *
from django.shortcuts import get_object_or_404
from .forms import *
import uuid
from .momo_utils import *
from .utils import *
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import get_token
import json
import base64
from .decorators import * 
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import get_backends
from django.db.models import Q
from django.db import transaction
from .authentication import EmailOrPhoneBackend  # Import the custom backend
from django.utils.timezone import now, localtime, make_aware
from django.utils.dateparse import parse_datetime
from apscheduler.schedulers.background import BackgroundScheduler
from django.views import View
from django.views.decorators.http import require_POST, require_GET
from datetime import datetime, timedelta, time, date
import random
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.http import JsonResponse,FileResponse,Http404
from .utils import *
import mimetypes
import markdown
from wsgiref.util import FileWrapper
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
# from django.contrib.auth.forms import CustomSetPasswordForm
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt



User = get_user_model()

def get_first_exam_id():
    first_exam = Exam.objects.filter(exam_type__name__icontains='ibivanze', for_scheduling=False).order_by('created_at').first()
    return first_exam.id if first_exam else None


def home(request):
    context = {}
    return render(request, 'home.html', context)


@redirect_authenticated_users
def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.save()
            messages.success(request, 'Urakoze kwiyandikisha muri Rwanda Driving College')
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('payment')
        else:
            messages.error(request, "Habayeho amakosa, reba ko wujuje neza.")
    else:
        form = RegisterForm()
    return render(request, 'registration/register.html', {'form': form})


def check_unique_field(request):
    field = request.GET.get("field")
    value = request.GET.get("value")
    response = {"exists": False}

    if field == "phone_number" and value:
        
        if len(value) >= 10:
            response["exists"] = User.objects.filter(phone_number__icontains=value).exists()

    return JsonResponse(response)


def whatsapp_consent(request):
    #Redirect if the user has already given consent
    if request.user.whatsapp_consent:
        return redirect('home')

    # Get the newly registered user from the session
    user_id = request.session.get('new_user_id')
    if not user_id:
        return redirect('register')

    try:
        user = UserProfile.objects.get(id=user_id)
    except UserProfile.DoesNotExist:
        messages.error(request, 'User not found. Please register again.')
        return redirect('register')

    if request.method == 'POST':
        form = WhatsAppConsentForm(request.POST)

        if form.is_valid():
            
            if form.cleaned_data['consent'] == 'yes':
                user.whatsapp_consent = True
                user.whatsapp_notifications = True
                phone = form.cleaned_data.get('whatsapp_number')
                if phone:
                    valid_phone = validate_phone_number(phone)
                    
                    if not valid_phone:
                        messages.error(request, 'Niba uhitampo yego, Andika nimero ya whatsapp neza!')
                        return render(request, 'registration/whatsapp_consent.html', {'form': form, 'user': user})
                    
                    user.whatsapp_number = phone
                    user.save(update_fields=['whatsapp_number'])                                       
                    notify_admin(f"{user.name} consented to WhatsApp notifications with number: {phone}")
                    messages.success(request, "Wemeye kubona ubutumwa  bw'ikizamini gishya kuri WhatsApp. Urakoze!")
            else:
                user.whatsapp_consent = False
                user.whatsapp_notifications = False
                messages.info(request, "Urakoze kwiyandikisha, amahirwe masa mu masomo yawe!")

            user.save()
            return redirect('home')

    else:
        form = WhatsAppConsentForm()

    return render(request, 'registration/whatsapp_consent.html', {
        'form': form,
        'user': user
    })


@redirect_authenticated_users
def verify_otp(request, user_id):
    # Fetch the UserProfile instance
    user_profile = get_object_or_404(UserProfile, id=user_id)
    if request.method == 'POST':
        otp = request.POST.get('otp')
        if user_profile.verify_otp(otp):
            user_profile.otp_verified = True
            user_profile.save()
            authenticated_user = authenticate(
                request,
                username=user_profile.phone_number or user_profile.email,
                password=user_profile.password  # Ensure the correct password is stored
            )


            if user_profile.phone_number == "":
                    user_profile.phone_number = None
                    user_profile.save(update_fields=["phone_number"])

            backend = get_backends()[0]
            user_profile.backend = f"{backend.__module__}.{backend.__class__.__name__}"
            login(request, user_profile)
            
            # Keep session active
            update_session_auth_hash(request, user_profile)

            messages.success(request, 'Kwemeza email yawe byakunze. uhawe ikaze!')
            return redirect('home')
        else:
            messages.error(request, 'Code ntago ariyo, ongera ugerageze.')
    return render(request, 'registration/verify_otp.html', {'user': user_profile})


@redirect_authenticated_users
def login_view(request):
    page='login'
    
    # show_modal = request.GET.get('login') is not None
    if request.method == "POST":
        form = LoginForm(request.POST)
        
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password"]

            # Fetch user by email or phone number
             # Normalize phone number if needed
            if "@" not in username:  
                username = EmailOrPhoneBackend().normalize_phone_number(username)

            # Fetch user by email or phone number
            user = UserProfile.objects.filter(Q(phone_number=username) | Q(email=username)).first()
            if user:
                # Ensure phone_number is set to None if empty
                if user.phone_number == "":
                    user.phone_number = None
                    user.save(update_fields=["phone_number"])
                
                
                authenticated_user = authenticate(request, username=username, password=password)
                
                if authenticated_user:
                    login(request, authenticated_user)
                    messages.success(request, "Kwinjira bikozwe neza cyane! Ikaze nanone.")
                    return redirect("home")
                else:
                    messages.error(request, "Ijambobanga ritariryo, ongera ugerageze.")
            else:
                register_link = mark_safe('<a href="/register" class="alert-link">Hanga konti</a>')
                messages.error(request, f"Iyi konti ntago ibaho, Gusa wayihanga. {register_link}")

        # Handle form validation errors
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field.capitalize()}: {error}")

    else:
        form = LoginForm()
        
    context = {
        "form": form,
        "page":page
    }
    return render(request, "base.html",context)


@require_POST
@login_required(login_url='login')
def user_logout(request):
    logout(request)
    messages.info(request, "Gusohoka byakunze.")
    return redirect('login')


@csrf_exempt
def password_reset(request):
    
    if request.method == "POST":
        phone_number = clean_phone_number(request.POST.get("phone_number"))

        if not phone_number:
            messages.error(request, "Andika numero ya telefone.")
            return redirect("password_reset")

        try:
            # Find user by phone
            user = UserProfile.objects.get(phone_number=phone_number)
        except UserProfile.DoesNotExist:
            messages.error(request, "Nta konti ifunguye kuri iyi nimero ya telefone. Ongera usuzume neza!")
            return redirect("password_reset")

        # Generate token and reset link
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        reset_url = request.build_absolute_uri(
            reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
        )

        # Send the link to admin (not to user)
        notify_admin(f"🔐 Password reset request for {user.name} ({user.phone_number})\nLink: {reset_url}")

        messages.success(
            request,
            "Link yo guhindura ijambobanga yoherejwe, reba kuri WhatsApp cyangwa sms yawe. Niba utabona link, saba ubufasha 0785287885.",
        )
        return redirect("login")

    return render(request, "registration/password_reset.html")

def password_reset_confirm(request, uidb64, token):
    """
    Step 2: User (or admin) opens the reset link and sets a new password.
    """
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = UserProfile.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, UserProfile.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if request.method == "POST":
            form = CustomSetPasswordForm(user, request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Ijambo ry'ibanga ryahinduwe neza. rikoreshe winjira.")
                return redirect("login")
        else:
            form = CustomSetPasswordForm(user)
        return render(request, "registration/password_reset_confirm.html", {"form": form})
    else:
        messages.error(request, "Link ntabwo ikiri valid cyangwa yararenze igihe.")
        return redirect("login")


@login_required
@subscription_required
def secure_download(request, course_id):
    try:
        course = Course.objects.get(id=course_id)
        user = request.user

        # Authorization logic
        if user.is_subscribed and user.subscription.plan.plan.lower() in ['vip', 'weekly']:
            return FileResponse(course.course_file.open('rb'), as_attachment=True)
        else:
            raise PermissionError("Unauthorized download attempt.")

    except (Course.DoesNotExist, PermissionError):
        raise Http404("You do not have permission to access this file.")

@login_required
@subscription_required
def secure_stream(request, course_id):
    try:
        course = Course.objects.get(id=course_id)
        user = request.user

        if not course.course_file:
            raise Http404("No file found.")

        if user.is_subscribed and user.subscription.plan.plan.lower() in ['vip', 'weekly', 'daily']:
            mime_type, _ = mimetypes.guess_type(course.course_file.name)
            wrapper = FileWrapper(course.course_file.open('rb'))
            return FileResponse(wrapper, content_type=mime_type or 'application/octet-stream')
        else:
            raise PermissionError("Unauthorized")
    except (Course.DoesNotExist, PermissionError):
        raise Http404("Access denied.")


@login_required(login_url='login')
@subscription_required
def course_detail(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not course.course_file:
        messages.error(request, "This course does not have a file associated with it.")
        return redirect('home')
    # Convert markdown to HTML
    description_html = mark_safe(markdown.markdown(course.description))

    return render(request, 'courses/course_detail.html', {
        'course': course,
        'description_html': description_html
    })

@login_required
def courses(request):
    courses = Course.objects.all()
    query = request.GET.get('q')
    
    context = {
        'courses': courses,
        'query': query or '',
    }
    if query:
        courses = courses.filter(title__icontains=query)
        context['courses'] = courses
    return render(request, 'courses/courses.html', context)


def navbar(request):
    # Get unique exam types that have exams
    exam_types = ExamType.objects.filter(exam__isnull=False, exam__for_scheduling=False).distinct().order_by('order')
    
    # Prefetch related exams for each type
    exam_types = exam_types.prefetch_related('exam_set')
    num = exam_types.count()
    
    context = {
        'exam_types': exam_types,
        'num':num
    }
    return render(request, 'default-navbar.html', context)

class SubscriptionRequiredView(View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_subscribed and not request.user.is_staff:
            messages.error(request, "Gura ifatabuguzi kugirango ubashe gukomeza!")
            return redirect('subscription')
        return super().dispatch(request, *args, **kwargs)


@login_required(login_url='login')
@subscription_required
def exam_detail(request, pk=None):
    # 1️⃣ Only create or pick exam if no pk provided
    if not pk:
        completed_exam_ids = list(
            UserExam.objects.filter(user=request.user, completed_at__isnull=False)
            .values_list('exam_id', flat=True)
        )

        available_exam_ids = list(
            Exam.objects.filter(for_scheduling=False).values_list('id', flat=True)
        )

        next_exam_id = next(
            (eid for eid in available_exam_ids if eid not in completed_exam_ids),
            None
        )

        if next_exam_id:
            exam_obj = Exam.objects.get(pk=next_exam_id)
        elif available_exam_ids:
            exam_obj = Exam.objects.get(pk=available_exam_ids[0])
        else:
            # No available exams → create one
            exam_created, created_exam_id = auto_create_exams(1)
            exam_obj = Exam.objects.get(pk=created_exam_id[0])

        # 🔁 Redirect to proper URL with pk
        return redirect('exam_detail', pk=exam_obj.pk)

    # 2️⃣ If pk provided, get that exam
    exam_obj = get_object_or_404(Exam, pk=pk)

    # 3️⃣ Prevent access to unpublished scheduled exams
    if (
        exam_obj.for_scheduling
        and hasattr(exam_obj, 'scheduledexam')
        and not exam_obj.scheduledexam.is_published
    ):
        return render(request, '404.html', status=404)

    # 4️⃣ Render the exam detail page
    return render(request, 'exams/exam_detail.html', {'exam': exam_obj})


@staff_member_required
def exam_schedule_view(request):
    selected_time = request.GET.get('time')
    try:
        hour, minute = map(int, selected_time.split(':'))
        if not (6 <= hour <= 21):
            raise ValueError("Time not within allowed range")
    except (ValueError, AttributeError):
        messages.error(request, "Invalid time provided.")
        return redirect('error_page')

    is_available = check_exam_availability(hour)
    context = {
        'selected_time': f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}",
        'is_available': is_available
    }
    return render(request, 'exams/exam_schedule.html', context)

def scheduled_hours(request):
    now = localtime(timezone.now())
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    exams_scheduled = ScheduledExam.objects.filter(
        scheduled_datetime__range=(start_of_day, end_of_day)
    )

    current_hour = now.hour
    pending = True
    
    if exams_scheduled.exists():
        for exam in exams_scheduled:
            if exam.scheduled_datetime.hour > current_hour:
                pending = True
                break

    completed_exam_ids = []
    if request.user.is_authenticated:
        completed_exam_ids = UserExam.objects.filter(
            user=request.user,
            completed_at__isnull=False
        ).values_list('exam_id', flat=True)

    context = {
        'exams_scheduled': exams_scheduled,
        'now': now,
        'current_hour': current_hour,
        'pending': pending,
        'completed_exam_ids': list(completed_exam_ids),
    }

    return render(request, 'scheduled_hours.html', context)

@require_GET
def check_exam_status(request, exam_id):
    try:
        exam = ScheduledExam.objects.get(id=exam_id)
        exam_time = timezone.localtime(exam.scheduled_datetime)
        return JsonResponse({
            "is_published": exam.is_published,
            "exam_url": reverse('exam_detail', kwargs={'pk': exam.exam.id}),  # Changed to kwargs
            "exam_time": exam_time.strftime("%H:00"),
            "remaining_time": exam.remaining_time

        })
    except ScheduledExam.DoesNotExist:  # Changed to match model name
        return JsonResponse({"error": "Exam not found"}, status=404)

def exam_timer(request, exam_id):
    try:
        scheduled_exam = ScheduledExam.objects.get(exam_id=exam_id)
        time_remaining = (scheduled_exam.scheduled_datetime - timezone.now()).total_seconds()
        return JsonResponse({'time_remaining': max(time_remaining, 0)})
    except ScheduledExam.DoesNotExist:
        return JsonResponse({'error': 'Exam not found'}, status=404)

@login_required(login_url='login')
def exams_by_type(request, exam_type):
    returned_exams = Exam.objects.filter(
        for_scheduling=False,
        exam_type__name=exam_type
    ).order_by('-updated_at')

    # Dictionary of completed exams: {exam_id: completed_at}
    completed_exams = UserExam.objects.filter(
        user=request.user,
        completed_at__isnull=False
    ).values('exam_id', 'completed_at')

    completed_exam_map = {
        item['exam_id']: item['completed_at'] for item in completed_exams
    }

    context = {
        'exam_type': exam_type,
        'returned_exams': returned_exams,
        'completed_exam_map': completed_exam_map,
        'counted_exams': returned_exams.count(),
    }    
    return render(request, "exams/same_exams.html", context)

@login_required(login_url='login')
@subscription_required
def ajax_question(request, exam_id, question_number):
    exam = get_object_or_404(Exam, id=exam_id)
    questions = list(exam.questions.all())
    total_questions = len(questions)
    question = questions[question_number - 1]
    
    # Get choices
    choices = []
    for i in range(1, 5):
        choice_text = getattr(question, f'choice{i}_text', None)
        choice_sign = getattr(question, f'choice{i}_sign', None)
        if choice_text:
            choices.append({'type': 'text', 'content': choice_text, 'id': i})
        elif choice_sign:
            choices.append({'type': 'image', 'content': choice_sign.image_url, 'id': i})

    context = {
        'exam': exam,
        'question': question,
        'question_number': question_number,
        'total_questions': total_questions,
        'choices': choices,
        'questions': questions,
    }

    html = render_to_string('partials/question_block.html', context, request=request)
    return JsonResponse({'html': html})


@login_required(login_url='login')
@subscription_required
def exam(request, exam_id, question_number):
    exam = get_object_or_404(Exam, id=exam_id)
    questions = list(exam.questions.all())
    total_questions = len(questions)

    user_exam, created = UserExam.objects.get_or_create(
        user=request.user,
        exam=exam,
        defaults={'score': 0, 'completed_at': None, 'started_at': timezone.now()}
    )
    
    if exam.for_scheduling and hasattr(exam, 'scheduledexam') and not exam.scheduledexam.is_published:
        return render(request, '404.html', status=404)

    if user_exam.completed_at:
        return redirect('retake_exam', exam_id=exam_id)

    if question_number < 1 or question_number > total_questions:
        messages.error(request, "Invalid question number.")
        return redirect('exam', exam_id=exam_id, question_number=1)

    current_question = questions[question_number - 1]

    # Time left for countdown
    if not request.user.is_staff:
        exam_end_time = (user_exam.started_at + timedelta(minutes=exam.duration)).timestamp()

    # Initialize answer session if not present
    if 'answers' not in request.session:
        request.session['answers'] = {}

    # Handle answer submission and navigation
    if request.method == 'POST':
        user_answer = request.POST.get('answer')
        if user_answer:
            request.session['answers'][str(current_question.id)] = user_answer
            request.session.modified = True

        if 'next' in request.POST and question_number < total_questions:
            return redirect('exam', exam_id=exam_id, question_number=question_number + 1)
        elif 'previous' in request.POST and question_number > 1:
            return redirect('exam', exam_id=exam_id, question_number=question_number - 1)
        
        elif 'submit' in request.POST:
            score = 0
            for question in questions:
                correct_choice = question.correct_choice
                user_choice = request.session['answers'].get(str(question.id))
                if user_choice and int(user_choice) == correct_choice:
                    score += 1
                UserExamAnswer.objects.update_or_create(
                    user_exam=user_exam,
                    question=question,
                    defaults={'selected_choice_number': user_choice}
                )

            user_exam.score = score
            user_exam.completed_at = timezone.now()

            try:
                user_exam.save()
                if hasattr(request.user, 'subscription'):
                    request.user.subscription.record_exam_taken
                    
            except ValidationError as e:
                messages.error(request, str(e))
                return redirect('subscription')

            request.session.pop('answers', None)
            messages.success(request, f"Ikizamini cyarangiye! Ugize amanota: {score}/{total_questions}.")
            return redirect('exam_results', user_exam_id=user_exam.id)

        elif 'go_to' in request.POST:
            go_to_question = int(request.POST['go_to'])
            if 1 <= go_to_question <= total_questions:
                return redirect('exam', exam_id=exam_id, question_number=go_to_question)
    q_nums = range(1, total_questions + 1)

    # Prepare choices for current question
    choices = []
    for i in range(1, 5):
        choice_text = getattr(current_question, f'choice{i}_text', None)
        choice_sign = getattr(current_question, f'choice{i}_sign', None)
        if choice_text:
            choices.append({'type': 'text', 'content': choice_text, 'id': i})
        elif choice_sign:
            choices.append({'type': 'image', 'content': choice_sign.image_url, 'id': i})

    context = {
        'exam': exam,
        'question': current_question,
        'question_number': question_number,
        'q_nums': q_nums,
        'total_questions': total_questions,
        'choices': choices,
        'exam_end_time': exam_end_time if not request.user.is_staff else None,
        'exam_duration': exam.duration * 60,
        'user_exam': user_exam,
        'questions': questions,
    }

    return render(request, 'exams/exam.html', context)

@login_required(login_url='login')
def exam_results(request, user_exam_id):
    
    user_exam = get_object_or_404(UserExam, id=user_exam_id, user=request.user)
    
    # if not request.user.is_subscribed or not request.user.subscription.exam_taken == 1 and not user_exam.exam.id == get_first_exam_id():
    #     messages.error(request, mark_safe(
    #         f"<span>Iki kizamini ufite amanota</span> {user_exam.score}<br><h6>Gura ifatabuguzi kugirango ubashe kureba byose!</h6>"
    #     ))
    #     return redirect('subscription')
    answers = UserExamAnswer.objects.filter(user_exam=user_exam).select_related('question')

    context = {
        'user_exam': user_exam,
        'answers': answers,
        'total_questions': user_exam.exam.questions.count(),
        'score': user_exam.score,
        'time_taken' : user_exam.time_taken,
        'percentage' : user_exam.percent_score,
        'decision' : user_exam.is_passed,
    }
    return render(request, 'exams/exam_results.html', context)

@login_required(login_url='login')
@subscription_required
def retake_exam(request, exam_id):
    if not request.user.is_subscribed and not request.user.is_staff: 
        messages.error(request, mark_safe(
            "<h2>Gura ifatabuguzi kugirango ubashe gusubirampo ikizamini!</h2>"
        ))
        return redirect('subscription')
    
    exam = get_object_or_404(Exam, id=exam_id)
    if exam.for_scheduling and hasattr(exam, 'scheduledexam') and not exam.scheduledexam.is_published:
        return render(request, '404.html', status=404)
    user_exam = get_object_or_404(UserExam, exam=exam, user=request.user)

    if not user_exam.completed_at:
        return redirect('exam', exam_id=exam_id, question_number=1)

    if request.method == 'POST':
        user_exam.started_at = timezone.now()
        user_exam.completed_at = None
        user_exam.score = 0
        user_exam.save()

        if 'answers' in request.session:
            del request.session['answers']

        messages.info(request, "Gusubirampo ikizamini byemeye. amahirwe masa!")
        return redirect('exam', exam_id=exam_id, question_number=1)

    context = {
        'exam': exam,
        'user_exam': user_exam,
    }
    return render(request, 'exams/confirm_retake_exam.html', context)

def get_weekly_scheduled_exams():
    now = timezone.now()
    start_of_week = now - timedelta(days=now.weekday() + 1)  # Monday
    end_of_week = start_of_week + timedelta(days=7)      # Sunday

    return ScheduledExam.objects.filter(
        scheduled_datetime__range=(start_of_week, end_of_week),
        scheduled_datetime__lte=now
    ).select_related('exam', 'exam__exam_type').order_by('-scheduled_datetime')

@login_required(login_url='login')
def weekly_exams(request):
    exams = get_weekly_scheduled_exams()

    # Get a list of tuples: (exam_id, completed_at)
    user_exam_data = UserExam.objects.filter(
        user=request.user,
        completed_at__isnull=False
    ).values_list('exam_id', 'completed_at')

    # Convert to a dictionary: {exam_id: completed_at}
    attempted_exams = {exam_id: completed_at for exam_id, completed_at in user_exam_data}

    # Attach status and time to each exam
    for exam in exams:
        exam_id = exam.exam.id
        exam.attempted = exam_id in attempted_exams
        exam.completed_at = attempted_exams.get(exam_id)

    context = {
        'exams': exams,
    }
    return render(request, 'exams/weekly_exams.html', context)


def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        contact_method = request.POST.get('contact_method')
        email = request.POST.get('email', '').strip()
        whatsapp = request.POST.get('whatsapp', '').strip()
        message_text = request.POST.get('message')

        if contact_method == 'email' and not email:
            messages.error(request, "Andika imeyili yawe nkuko wabihisempo.")
            return redirect('contact')
        elif contact_method == 'whatsapp' and not whatsapp:
            messages.error(request, "Andika nimero ya WhatsApp nkuko wabihisempo.")
            return redirect('contact')
        elif not contact_method:
            messages.error(request, "Hitamo uburyo bwo kugusubizaho.")
            return redirect('contact')

        ContactMessage.objects.create(
            name=name,
            email=email if contact_method == 'email' else None,
            whatsapp_number=whatsapp if contact_method == 'whatsapp' else None,
            message=message_text
        )
        messages.success(request, "Ubutumwa bwawe bwoherejwe neza! Tuzagusubiza vuba.")
        return redirect('contact')

    return render(request, 'contact.html')

def get_unverified_subscription(user):
    subscription = Subscription.objects.filter(
        user=user, 
        otp_code__isnull=False,
        otp_verified=False).first()
    return subscription

# ---------------------
@login_required(login_url='login')
def payment(request):
    page = 'payment'
    plans=Plan.objects.all().order_by('price')
    context = {
        'plans': plans,
        'range_10': range(10),
        'first_exam_id': get_first_exam_id(),
        'page': page,
    }
    return render(request, 'payment.html', context)


@login_required(login_url='login')
def subscription_status(request): 
    page = 'subscription_status'
    plans = Plan.objects.all()
    unverified_subscription = get_unverified_subscription(request.user)
    context = {'page': page,
        'plans': plans,
        'range_10': range(10),
        'first_exam_id': get_first_exam_id(),
        'unverified_subscription' : unverified_subscription}    
    return render(request, 'payment.html', context)
# ---------------------
# Subscription and Payment Views
# ---------------------


@login_required(login_url='login')
@transaction.atomic
def payment_confirm(request):
   
    if request.method == 'POST':
        try:
            payeer_name = request.POST.get('payeer_name', '').strip()
            payeer_phone = request.POST.get('payeer_phone', '').strip()
            plan_choice = request.POST.get('plan', '').strip()
            whatsapp_number = request.POST.get('whatsapp_number', '').strip()
            
            
            # Validate phone numbers
            try:
                validate_phone_number(payeer_phone)
                validate_phone_number(whatsapp_number)
            except ValidationError as e:
                messages.error(request, str(e))
                return render(request, 'payment.html', {'first_exam_id': get_first_exam_id()})
            
            # Get plan
            try:
                plan = Plan.objects.get(price=plan_choice)
            except Plan.DoesNotExist:
                messages.error(request, "Server error")
                return render(request, 'payment.html', {'first_exam_id': get_first_exam_id()})
            
            # Create/update payment confirmation
            PaymentConfirm.objects.update_or_create(
                user=request.user,
                defaults={
                    'payeer_name': payeer_name,
                    'phone_number': payeer_phone,
                    'plan': plan,
                    'whatsapp_number': whatsapp_number,
                    'time': timezone.now()
                }            
            )            
            
            notify_admin(f"New payment confirmation from {request.user.name}, payeer name: {payeer_name}, plan: {plan}, whatsapp: {whatsapp_number}")
            
            messages.success(request, f"Kwemeza ubwishyu byoherejwe neza! Urakira igisubizo mu munota umwe.")
            return redirect('home')
            
        except Exception as e:
            messages.error(request, "An error occurred while processing your payment confirmation. Please try again.")
   

@login_required(login_url='/?login=true')
def subscription_view(request):
    # sub = request.user.subscription and request.user.subscription.expires_at > timezone.now().date()

    subscription, created = Subscription.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        plan_choice = request.POST.get('plan')
        phone_number = request.POST.get('phone_number')
        if plan_choice not in dict(plans):
            messages.error(request, "Ikiciro kitaricyo.")
            return redirect('subscription')

        try:
            selected_plan = Plan.objects.get(plan=plan_choice)
        except Plan.DoesNotExist:
            messages.error(request, "Ikiciro wahisempo ntikibaho.")
            return redirect('subscription')

        # This function should return (price, duration_days) for the selected plan.
        price, duration_days = set_price_and_duration(plan_choice)  # Ensure this helper exists.

        payment_response, transaction_id = request_momo_payment(phone_number, price)
        if "error" in payment_response:
            messages.error(request, payment_response["error"])
            return redirect('subscription')

        # Save transaction details
        subscription.plan = selected_plan  # ✅ Assign the Plan instance
        subscription.price = price
        subscription.duration_days = duration_days
        subscription.phone_number = phone_number
        subscription.transaction_id = transaction_id
        subscription.save()


        messages.info(request, "Kwemeza ubwishyu byoherejwe. reba kuri telefone wemeze.")
        return redirect('momo_payment_status', transaction_id=transaction_id)

    context = {
        'subscription': subscription,
        'plans': plans,
        # 'sub': sub
    }
    return render(request, 'subscription.html', context)

@login_required
def activate_subscription_view(request):
    context = {}
    unverified_subscription = get_unverified_subscription(request.user)
    if unverified_subscription:
        user_otp = unverified_subscription.otp_code
        context['user_otp'] = user_otp
    else:
        return redirect('subscription')

    if request.method == "POST":
        otp = request.POST.get("otp")
        try:
            subscription = Subscription.objects.get(user=request.user, otp_verified=False)
        except Subscription.DoesNotExist:
            otp_used = Subscription.objects.filter(user=request.user, otp_verified=True, otp_code=otp).exists()
            subscription = Subscription.objects.filter(user=request.user, otp_verified=True).first()
            otp_used_at = localtime(subscription.started_at).strftime("%d-%m-%Y Saa %H:%M") if otp_used else None
            
            expires_at = localtime(subscription.expires_at).strftime("%d-%m-%Y Saa %H:%M") if subscription else "N/A"
            contact = ""
            
            Error_type = f"Code wamaze kuyikoresha!!!" if otp_used else "Code ntago ariyo!!!"
            context.update({
                "show_modal": True,
                "Error_type": Error_type,
                "modal_title": f"Error: {Error_type}",                
                "modal_message": f'''                
                 <br> ifatabuguzi ryafunguwe Taliki:
                <strong>{otp_used_at}</strong> <br>
                kugeza Taliki: <strong>{expires_at}</strong>'''
                if otp_used else f"Ongera ugerageze!",
                "redirect_url": reverse("activate_subscription"),
            })
            return render(request, "activate_subscription.html", context)

        success, message, expires_at = subscription.verify_and_start(otp)
        if success:
            # Get human-readable plan name
            plan_display = Plan.plan_label
            today = timezone.now().date()
            expires_date = localtime(expires_at).strftime('%d-%m-%Y')
            expires_hour = localtime(expires_at).strftime('%H:%M')
            if expires_date == today:
                expires_date = ''
            else:
                expires_date = "Taliki " + expires_date 
                
            context.update({
                "show_modal": True,
                "modal_title": f"Ifatabuguzi <strong>'{plan_display}'</strong> riratangiye🎉",
                "modal_message": f'''{message} Ubu wemerewe kwiga no gukosora ibizamini ushaka kugeza <br> 
                <strong>{expires_date} Saa {expires_hour}</strong>''',
                "redirect_url": reverse("home"),
            })
        else:
            context.update({
                "show_modal": True,
                "modal_title": "Error",
                "modal_message": message,
                "redirect_url": reverse("subscription"),
            })

    return render(request, "activate_subscription.html", context)


def momo_payment(request):
    
    phone_number = request.GET.get("phone")
    amount = request.GET.get("amount")
    if not phone_number or not amount:
        return JsonResponse({"error": "Telefone n'igiciro birakenewe"}, status=400)

    payment_response, transaction_id = request_momo_payment(phone_number, amount)
    if "error" in payment_response:
        return JsonResponse(payment_response, status=500)
    return JsonResponse({"message": "Payment request sent", "transaction_id": transaction_id})


def momo_payment_status(request, transaction_id):
    if not transaction_id or transaction_id == "None":
        return JsonResponse({"error": "Invalid transaction ID"}, status=400)
    status = check_payment_status(transaction_id)
    return JsonResponse(status)


class PrivacyPolicyView(View):
    def get(self, request):
        return render(request, 'privacy_policy.html')


def base_view(request):
    
    context = {
        'current_year': datetime.datetime.now().year,
    }
    return render(request, 'base.html', context)

@staff_member_required
@require_POST
def undo_last_exam_action(request):
    exam_ids = request.session.get('undo_exam_ids', [])

    if exam_ids:
        Exam.objects.filter(id__in=exam_ids).delete()
        messages.success(request, "✅ Undo successful! Exams deleted.")
        request.session.pop('undo_exam_ids')
    else:
        messages.warning(request, "⚠️ No recent exams to undo.")

    return redirect('create_exam')


@login_required(login_url='login')
@staff_member_required
def create_exam_page(request):
    if request.method == 'POST':
        try:
            number = int(request.POST.get("number", 0))
            if number <= 0:
                raise ValueError("Number must be greater than 0")
            
            exams_created, created_exam_ids = auto_create_exams(number)
            request.session['undo_exam_ids'] = created_exam_ids
            request.session['show_undo'] = True  # Add flag

            messages.success(request, f"{exams_created} exam(s) created successfully!")
            return redirect('create_exam')
        except (ValueError, TypeError):
            messages.error(request, "Invalid number of exams.")

    # Show last 10 Ibivanze exams
    ibivanze_type = ExamType.objects.filter(name='Ibivanze').first()
    recent_exams = Exam.objects.filter(exam_type=ibivanze_type).order_by('-created_at')[:10]
    
    context = {
        'recent_exams': recent_exams,
        'show_undo': request.session.pop('show_undo', False),
        'has_undo_ids': bool(request.session.get('undo_exam_ids')),
    }
    return render(request, 'exams/create_exam.html', context)


@staff_member_required
def schedule_recent_exams(request):
    
    if request.method == 'POST':
        
        _ , message =  auto_schedule_recent_exams()

        messages.success(request, message)
        return redirect('auto_schedule_exams')  # Or redirect to a success page

    return render(request, 'exams/schedule_recent_exams.html')

# ---------------------
#404 Error Page
def custom_page_not_found(request, exception):
    
    context = {}
    return render(request, '404.html', context, status=404)


@csrf_exempt  # We exempt this view from CSRF since it handles CSRF failures
def csrf_failure(request, reason=""):
    ctx = {
        'reason': reason,
        'csrf_token': get_token(request),  # Generate new token
    }
    return render(request, '403.html', ctx, status=403)


@csrf_exempt
@login_required
def resend_otp(request, user_id):
    if request.method == "POST":
        user_profile = get_object_or_404(UserProfile, id=user_id)
        # Logic to resend OTP (e.g., send email or SMS)
        user_profile.send_otp_email()  # Assuming you have a method to send OTP
        return JsonResponse({"message": "OTP resent successfully."}, status=200)
    return JsonResponse({"error": "Invalid request."}, status=400)

@login_required
def check_unverified_subscription(request):
    has_unverified = None
    if not request.user.is_authenticated:
        return JsonResponse({'unverified': False, 'error': 'unauthenticated'}, status=401)
    if request.user.is_subscribed:
        has_unverified =False
    unverified_sub = get_unverified_subscription(request.user)
    if unverified_sub:
        has_unverified = True
    print(has_unverified)
    return JsonResponse({'unverified': has_unverified})